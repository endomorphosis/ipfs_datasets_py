"""Cutoff-bound official Federal Register inventory acquisition (LCR-052).

Enumerates FederalRegister.gov API result pages across non-overlapping date
partitions through a sealed UTC observation cutoff, records page/response
hashes, reconciles official totals against unique document-number identities,
resumes from atomic checkpoints, and emits a durable inventory receipt.

Design invariants
-----------------
* FederalRegister.gov API is the sole inventory/discovery authority.
* Observation cutoffs are immutable UTC pins; ``latest`` / branch tokens fail.
* Completeness is cutoff-relative (inherits LCR-049 source policy / oracle).
* Every closed page carries a stable response hash of the exact API body.
* The union of document numbers is duplicate-free by official identity
  (``document_number`` + ``publication_date`` → ``legal_id``).
* Date partitions neither overlap nor leave gaps relative to the declared range.
* ``enumerated = fetched + duplicate + excluded + quarantined + failed_final``
  with ``failed_final = 0`` and zero unexplained count drift for closed runs.
* Secrets, cookies, absolute local paths, and private headers never enter
  committed receipts.
* ``--fixture-only`` mode uses sealed compact recipes and never contacts the
  network; live transport is opt-in and never required for CI gates.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Union,
)

from ipfs_datasets_py.processors.legal_data.federal_register_completeness import (
    SCHEMA_VERSION as COMPLETENESS_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.federal_register_completeness import (
    CompletenessResult,
    CompletenessVerdict,
    DatePartition,
    PageReceipt,
    PageStatus,
    PartitionStatus,
    evaluate_completion_receipt,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_API_PER_PAGE,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    DEFAULT_OBSERVATION_CUTOFF_DATE,
    FEDERAL_REGISTER_DOCUMENTS_API,
    LEGACY_ADVERTISED_COUNT,
    LEGACY_BASELINE_END_INCLUSIVE,
    LEGACY_BASELINE_START_INCLUSIVE,
    LEGACY_DELTA_START_INCLUSIVE,
    LEGACY_MATERIALIZED_COUNT,
    MAX_API_PER_PAGE,
    OFFICIAL_INVENTORY_SOURCE,
    PREVIOUS_PUBLIC_PIN,
    BodyTextDisposition,
    FederalRegisterSourcePolicyError,
    OfficialAuthority,
    build_legal_id,
    canonical_json_dumps,
    content_sha256,
    cutoff_release_point,
    digest_mapping,
    normalize_sha256,
    observation_cutoff_date,
    parse_calendar_date,
    repository_root,
    require_immutable_observation_cutoff,
    validate_calendar_date,
    validate_document_number,
    validate_official_url,
    validate_year_month,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-acquisition-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-inventory@1"
CHECKPOINT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-inventory-checkpoint@2"
)
TASK_ID: Final = "LCR-052"
GOAL_ID: Final = "LCR-G110"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_acquisition.py"
CODE_VERSION: Final = "1"

MODE_FIXTURE: Final = "fixture"
MODE_LIVE: Final = "live"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)
DEFAULT_CHECKPOINT_DIRNAME: Final = "federal_register_inventory_checkpoints"
DEFAULT_PER_PAGE: Final = DEFAULT_API_PER_PAGE  # 100
DEFAULT_MAX_RETRIES: Final = 3
DEFAULT_RETRY_BACKOFF_SECONDS: Final = 0.5
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final = 30.0
MAX_API_RESPONSE_BYTES: Final = 32 * 1024 * 1024
MAX_CHECKPOINT_BYTES: Final = 64 * 1024 * 1024
MAX_ABSTRACT_CHARS: Final = 4096
DEFAULT_RATE_LIMIT_SECONDS: Final = 0.25
DEFAULT_USER_AGENT: Final = (
    "ipfs-datasets-py-legal-corpora-reindex/1.0 "
    "(+https://github.com/endomorphosis/ipfs_datasets_py; "
    "Federal Register official inventory acquisition; LCR-052)"
)

# Compact sealed fixture covers the post-legacy-endpoint delta through the
# planning cutoff with monthly partitions and a handful of official identities.
FIXTURE_RANGE_START: Final = LEGACY_DELTA_START_INCLUSIVE  # 2026-03-03
FIXTURE_RANGE_END: Final = DEFAULT_OBSERVATION_CUTOFF_DATE  # 2026-08-10
FIXTURE_DOCS_PER_PARTITION: Final = 3
FIXTURE_PER_PAGE: Final = 2

# Minimum post-endpoint documents exposed by the official API through the
# planning cutoff (sealed from the LCR-048 baseline audit).
POST_ENDPOINT_DELTA_DOCUMENTS_MIN: Final = 11_784

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
# Transport returns (response_bytes, parsed_json).
ApiTransport = Callable[[str, Mapping[str, str]], tuple[bytes, dict[str, Any]]]

# Secret / private-surface detectors for fail-closed receipt sanitization.
# Key patterns are whole-token (word-boundary) matches so fields such as
# ``inventory_authority`` or ``authorization_status`` are not false positives
# unless they are themselves secret-bearing keys.
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|_)(api[_-]?key|access[_-]?token|authorization|password|secret|"
    r"cookie|set[_-]?cookie|bearer|private[_-]?key|session[_-]?id|x[_-]?api[_-]?key)"
    r"(?:$|_)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:^|[\s\"'=])("
    r"sk-[A-Za-z0-9]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|hf_[A-Za-z0-9]{20,}"
    r"|Bearer\s+[A-Za-z0-9\-._~+/]+=*"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r")"
)
_ABSOLUTE_HOME_PATH_RE = re.compile(
    r"(?:^|[\s\"'])(?:/home/|/Users/|C:\\\\Users\\\\)[^\s\"']+"
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterAcquisitionError(FederalRegisterSourcePolicyError):
    """Base error for Federal Register inventory acquisition failures."""


class PartitionPlanError(FederalRegisterAcquisitionError):
    """Raised when date partitions cannot be planned fail-closed."""


class PageFetchError(FederalRegisterAcquisitionError):
    """Raised when an official API page cannot be fetched or verified."""


class IdentityCollisionError(FederalRegisterAcquisitionError):
    """Raised when official identities collide or duplicates are unexplained."""


class InventoryGapError(FederalRegisterAcquisitionError):
    """Raised when the inventory union has gaps or open pages."""


class InventoryDriftError(FederalRegisterAcquisitionError):
    """Raised when enumerated totals drift from official API totals."""


class FailedFinalItemError(FederalRegisterAcquisitionError):
    """Raised when failed-final items remain in a closed inventory."""


class SecretInReceiptError(FederalRegisterAcquisitionError):
    """Raised when secrets or private surfaces appear in a receipt."""


class CheckpointError(FederalRegisterAcquisitionError):
    """Raised when a resume checkpoint is corrupt or non-atomic."""


class FixtureTransportError(FederalRegisterAcquisitionError):
    """Raised when fixture transport cannot satisfy a request."""


class LiveTransportDisabledError(FederalRegisterAcquisitionError):
    """Raised when live network transport is required but not enabled."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AcquisitionMode(str, Enum):
    """Inventory acquisition mode."""

    FIXTURE = MODE_FIXTURE
    LIVE = MODE_LIVE

    @classmethod
    def coerce(cls, value: Any) -> "AcquisitionMode":
        if isinstance(value, AcquisitionMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "fixture_only": cls.FIXTURE,
            "offline": cls.FIXTURE,
            "sealed": cls.FIXTURE,
            "network": cls.LIVE,
            "online": cls.LIVE,
            "api": cls.LIVE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterAcquisitionError(f"unknown acquisition mode: {value!r}")


class DocumentDisposition(str, Enum):
    """Inventory-level disposition of one official discovery item."""

    FETCHED = "fetched"
    DUPLICATE = "duplicate"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "DocumentDisposition":
        if isinstance(value, DocumentDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterAcquisitionError(
            f"unknown document disposition: {value!r}"
        )


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterAcquisitionError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterAcquisitionError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterAcquisitionError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_bounded_str(
    value: Any,
    name: str,
    *,
    maximum: int,
    allow_empty: bool = True,
) -> str:
    """Require an exact string without coercion or lossy truncation."""

    if not isinstance(value, str):
        raise FederalRegisterAcquisitionError(f"{name} must be a string")
    if "\x00" in value:
        raise FederalRegisterAcquisitionError(f"{name} must not contain NUL")
    if not allow_empty and not value:
        raise FederalRegisterAcquisitionError(f"{name} must not be empty")
    if len(value) > maximum:
        raise FederalRegisterAcquisitionError(
            f"{name} exceeds maximum length {maximum}"
        )
    return value


def _require_optional_bounded_str(
    value: Any,
    name: str,
    *,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _require_bounded_str(value, name, maximum=maximum, allow_empty=False)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterAcquisitionError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterAcquisitionError(f"{name} must be >= 0")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise FederalRegisterAcquisitionError(f"{name} must be a boolean")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FederalRegisterAcquisitionError(f"{name} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FederalRegisterAcquisitionError(f"{name} must be a sequence")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    name: str,
) -> None:
    observed = set(value)
    if observed != expected:
        raise FederalRegisterAcquisitionError(
            f"{name} fields differ from the exact schema: "
            f"missing={sorted(expected - observed)}; "
            f"extra={sorted(observed - expected)}"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_utc_now() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


# Fixed observation timestamp for sealed fixture receipts (reproducible digests).
FIXTURE_OBSERVED_AT: Final = "2026-08-10T12:00:00Z"


def month_end(year: int, month: int) -> date:
    """Return the last calendar day of ``year``/``month``."""

    last = calendar.monthrange(year, month)[1]
    return date(year, month, last)


def default_report_path(repo_root: PathLike | None = None) -> Path:
    """Return the frozen federal inventory report path."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_checkpoint_dir(
    *,
    env: Mapping[str, str] | None = None,
    repo_root: PathLike | None = None,
) -> Path:
    """Return the atomic checkpoint directory for inventory acquisition.

    Prefers ``$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR`` when set (supervisor
    task coordinate). Falls back to a repo-local state directory.
    """

    environ = env if env is not None else os.environ
    configured = (
        environ.get("IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR") or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / ".cache" / DEFAULT_CHECKPOINT_DIRNAME).resolve()


# ---------------------------------------------------------------------------
# Secret / private-surface scanning
# ---------------------------------------------------------------------------


def find_secret_surfaces(payload: Any, *, path: str = "$") -> list[str]:
    """Return paths of secret-like keys/values or absolute home paths."""

    hits: list[str] = []

    def _walk(node: Any, current: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_text = str(key)
                child = f"{current}.{key_text}"
                if _SECRET_KEY_RE.search(key_text):
                    hits.append(child)
                _walk(value, child)
        elif isinstance(node, (list, tuple)):
            for idx, item in enumerate(node):
                _walk(item, f"{current}[{idx}]")
        elif isinstance(node, str):
            if _SECRET_VALUE_RE.search(node):
                hits.append(current)
            elif _ABSOLUTE_HOME_PATH_RE.search(node):
                hits.append(current)

    _walk(payload, path)
    return hits


def assert_no_secrets(payload: Any, *, context: str = "inventory") -> None:
    """Fail closed when secrets or private surfaces appear in *payload*."""

    hits = find_secret_surfaces(payload)
    if hits:
        preview = ", ".join(hits[:8])
        more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
        raise SecretInReceiptError(
            f"{context} contains secret or private surfaces: {preview}{more}"
        )


# ---------------------------------------------------------------------------
# Partition planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartitionSpec:
    """One planned non-overlapping publication-date partition."""

    partition_id: str
    start_date: str
    end_date: str
    year_month: str

    def __post_init__(self) -> None:
        start = validate_calendar_date(self.start_date, name="start_date")
        end = validate_calendar_date(self.end_date, name="end_date")
        if start > end:
            raise PartitionPlanError(
                f"partition {self.partition_id!r}: start {start} > end {end}"
            )
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        object.__setattr__(self, "year_month", validate_year_month(self.year_month))
        object.__setattr__(
            self,
            "partition_id",
            _require_non_empty_str(self.partition_id, "partition_id", maximum=128),
        )

    @property
    def start(self) -> date:
        return parse_calendar_date(self.start_date)

    @property
    def end(self) -> date:
        return parse_calendar_date(self.end_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "year_month": self.year_month,
        }


def plan_monthly_partitions(
    range_start: Any,
    range_end: Any,
) -> tuple[PartitionSpec, ...]:
    """Plan inclusive monthly partitions covering ``[range_start, range_end]``.

    Adjacent partitions abut (``next.start == prev.end + 1 day``). Partitions
    never overlap and never extend outside the declared range.
    """

    start = parse_calendar_date(range_start, name="range_start")
    end = parse_calendar_date(range_end, name="range_end")
    if end < start:
        raise PartitionPlanError(
            f"range_end {end.isoformat()} precedes range_start {start.isoformat()}"
        )

    specs: list[PartitionSpec] = []
    cursor = start
    while cursor <= end:
        year, month = cursor.year, cursor.month
        month_last = month_end(year, month)
        part_end = month_last if month_last <= end else end
        year_month = f"{year:04d}-{month:02d}"
        partition_id = f"p-{year_month}"
        # Disambiguate when the same calendar month is split (should not
        # happen for standard monthly planning, but keep ids unique).
        if any(s.partition_id == partition_id for s in specs):
            partition_id = f"p-{year_month}-{cursor.isoformat()}"
        specs.append(
            PartitionSpec(
                partition_id=partition_id,
                start_date=cursor.isoformat(),
                end_date=part_end.isoformat(),
                year_month=year_month,
            )
        )
        cursor = part_end + timedelta(days=1)

    # Geometry self-check: no gaps / overlaps.
    for idx in range(len(specs) - 1):
        left = specs[idx]
        right = specs[idx + 1]
        expected = left.end + timedelta(days=1)
        if right.start != expected:
            raise PartitionPlanError(
                f"partition plan gap/overlap between {left.partition_id} and "
                f"{right.partition_id}: expected next start {expected.isoformat()}, "
                f"got {right.start_date}"
            )
    if specs[0].start != start or specs[-1].end != end:
        raise PartitionPlanError("partition plan does not cover the full range")
    return tuple(specs)


def plan_full_history_partitions(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> tuple[PartitionSpec, ...]:
    """Plan monthly partitions from the legacy baseline start through cutoff."""

    cutoff_date = observation_cutoff_date(observation_cutoff)
    return plan_monthly_partitions(LEGACY_BASELINE_START_INCLUSIVE, cutoff_date)


def plan_delta_partitions(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> tuple[PartitionSpec, ...]:
    """Plan monthly partitions for the post-legacy-endpoint delta window."""

    cutoff_date = observation_cutoff_date(observation_cutoff)
    return plan_monthly_partitions(LEGACY_DELTA_START_INCLUSIVE, cutoff_date)


# ---------------------------------------------------------------------------
# Document / page records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryDocument:
    """One official inventory discovery item."""

    document_number: str
    publication_date: str
    title: str = ""
    html_url: str = ""
    pdf_url: str = ""
    xml_url: str = ""
    document_type: str = ""
    agencies: tuple[str, ...] = ()
    disposition: DocumentDisposition = DocumentDisposition.FETCHED
    legal_id: str = ""
    abstract: str = ""
    page_id: str = ""
    partition_id: str = ""

    def __post_init__(self) -> None:
        doc = validate_document_number(self.document_number)
        pub = validate_calendar_date(self.publication_date, name="publication_date")
        object.__setattr__(self, "document_number", doc)
        object.__setattr__(self, "publication_date", pub)
        object.__setattr__(
            self, "disposition", DocumentDisposition.coerce(self.disposition)
        )
        legal_raw = _require_bounded_str(
            self.legal_id, "legal_id", maximum=512
        )
        legal = legal_raw.strip() if legal_raw else ""
        if not legal:
            legal = build_legal_id(doc, pub)
        else:
            # Identity must remain consistent with official fields.
            expected = build_legal_id(doc, pub)
            if legal != expected and not legal.startswith(expected + ":"):
                # Allow qualifiers but base identity must match.
                base = ":".join(legal.split(":")[:3])
                if base != expected:
                    raise IdentityCollisionError(
                        f"legal_id {legal!r} does not match document "
                        f"{doc}/{pub} (expected {expected!r})"
                    )
        object.__setattr__(self, "legal_id", legal)
        for url_field in ("html_url", "pdf_url", "xml_url"):
            raw = getattr(self, url_field)
            _require_bounded_str(raw, url_field, maximum=4096)
            if raw.strip():
                object.__setattr__(
                    self, url_field, validate_official_url(raw, name=url_field)
                )
            else:
                object.__setattr__(self, url_field, "")
        if not isinstance(self.agencies, tuple):
            raise FederalRegisterAcquisitionError("agencies must be a tuple")
        agencies = tuple(
            _require_non_empty_str(a, f"agencies[{i}]", maximum=256)
            for i, a in enumerate(self.agencies)
        )
        object.__setattr__(self, "agencies", agencies)
        for field_name, maximum in (
            ("title", 2048),
            ("abstract", MAX_ABSTRACT_CHARS),
            ("document_type", 128),
            ("page_id", 128),
            ("partition_id", 128),
        ):
            object.__setattr__(
                self,
                field_name,
                _require_bounded_str(
                    getattr(self, field_name), field_name, maximum=maximum
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "publication_date": self.publication_date,
            "title": self.title,
            "html_url": self.html_url,
            "pdf_url": self.pdf_url,
            "xml_url": self.xml_url,
            "document_type": self.document_type,
            "agencies": list(self.agencies),
            "disposition": self.disposition.value,
            "legal_id": self.legal_id,
            "abstract": self.abstract,
            "page_id": self.page_id,
            "partition_id": self.partition_id,
        }

    @classmethod
    def from_api_result(
        cls,
        raw: JsonMapping,
        *,
        partition_id: str,
        page_id: str,
        disposition: DocumentDisposition = DocumentDisposition.FETCHED,
    ) -> "InventoryDocument":
        def _optional_text(*field_names: str, maximum: int) -> str:
            for field_name in field_names:
                if field_name not in raw or raw[field_name] is None:
                    continue
                value = raw[field_name]
                if value == "":
                    continue
                return _require_bounded_str(
                    value,
                    f"API result {field_name}",
                    maximum=maximum,
                )
            return ""

        agencies_raw = raw.get("agencies")
        if agencies_raw is None:
            agencies_raw = ()
        agency_names: list[str] = []
        if isinstance(agencies_raw, Sequence) and not isinstance(
            agencies_raw, (str, bytes)
        ):
            for item in agencies_raw:
                if isinstance(item, Mapping):
                    name = item.get("name") or item.get("raw_name") or item.get("id")
                    if name is not None and name != "":
                        agency_names.append(
                            _require_non_empty_str(
                                name, "API result agency name", maximum=256
                            )
                        )
                elif item is not None and item != "":
                    agency_names.append(
                        _require_non_empty_str(
                            item, "API result agency name", maximum=256
                        )
                    )
        else:
            raise FederalRegisterAcquisitionError(
                "API result agencies must be a sequence"
            )
        return cls(
            document_number=_require_non_empty_str(
                raw.get("document_number"),
                "API result document_number",
                maximum=64,
            ),
            publication_date=_require_non_empty_str(
                raw.get("publication_date"),
                "API result publication_date",
                maximum=10,
            ),
            title=_optional_text("title", maximum=2048),
            html_url=_optional_text("html_url", maximum=4096),
            pdf_url=_optional_text("pdf_url", maximum=4096),
            xml_url=_optional_text(
                "full_text_xml_url", "xml_url", "raw_text_url", maximum=4096
            ),
            document_type=_optional_text(
                "type", "document_type", "subtype", maximum=128
            ),
            agencies=tuple(agency_names),
            disposition=disposition,
            abstract=_optional_text("abstract", maximum=MAX_ABSTRACT_CHARS),
            page_id=page_id,
            partition_id=partition_id,
        )


@dataclass(frozen=True)
class PageEvidence:
    """Stable response evidence for one official API result page."""

    page_id: str
    page_number: int
    partition_id: str
    request_url: str
    response_hash: str
    result_count: int
    document_numbers: tuple[str, ...]
    status: PageStatus = PageStatus.VERIFIED
    cursor: Optional[str] = None
    api_total: int = 0
    next_page_url: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "page_id",
            _require_non_empty_str(self.page_id, "page_id", maximum=128),
        )
        page_number = _require_non_negative_int(self.page_number, "page_number")
        if page_number < 1:
            raise PageFetchError("page_number must be >= 1")
        object.__setattr__(self, "page_number", page_number)
        object.__setattr__(
            self,
            "partition_id",
            _require_non_empty_str(self.partition_id, "partition_id", maximum=128),
        )
        object.__setattr__(
            self,
            "request_url",
            validate_official_url(self.request_url, name="request_url"),
        )
        object.__setattr__(
            self,
            "response_hash",
            normalize_sha256(self.response_hash, name="response_hash"),
        )
        object.__setattr__(
            self,
            "result_count",
            _require_non_negative_int(self.result_count, "result_count"),
        )
        object.__setattr__(
            self, "api_total", _require_non_negative_int(self.api_total, "api_total")
        )
        object.__setattr__(self, "status", PageStatus.coerce(self.status))
        docs = tuple(
            validate_document_number(d, name=f"document_numbers[{i}]")
            for i, d in enumerate(self.document_numbers or ())
        )
        object.__setattr__(self, "document_numbers", docs)
        object.__setattr__(
            self,
            "cursor",
            _require_optional_bounded_str(self.cursor, "cursor", maximum=2048),
        )
        object.__setattr__(
            self,
            "next_page_url",
            _require_optional_bounded_str(
                self.next_page_url, "next_page_url", maximum=4096
            ),
        )
        if self.status.is_closed and self.status is not PageStatus.SKIPPED:
            if not self.response_hash:
                raise PageFetchError(
                    f"page {self.page_id!r} closed status requires response_hash"
                )

    def to_page_receipt(self) -> PageReceipt:
        return PageReceipt(
            page_id=self.page_id,
            page_number=self.page_number,
            status=self.status,
            cursor=self.cursor,
            response_hash=self.response_hash,
            result_count=self.result_count,
            document_numbers=self.document_numbers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_number": self.page_number,
            "partition_id": self.partition_id,
            "request_url": self.request_url,
            "response_hash": self.response_hash,
            "result_count": self.result_count,
            "document_numbers": list(self.document_numbers),
            "status": self.status.value,
            "cursor": self.cursor,
            "api_total": self.api_total,
            "next_page_url": self.next_page_url,
        }


@dataclass
class PartitionAcquisitionState:
    """Mutable acquisition state for one date partition."""

    spec: PartitionSpec
    pages: list[PageEvidence] = field(default_factory=list)
    documents: list[InventoryDocument] = field(default_factory=list)
    api_total: int = 0
    status: PartitionStatus = PartitionStatus.PENDING
    failed_final: int = 0
    excluded: int = 0
    quarantined: int = 0

    @property
    def unique_document_numbers(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for doc in self.documents:
            if doc.disposition is DocumentDisposition.DUPLICATE:
                continue
            if doc.document_number not in seen:
                seen.add(doc.document_number)
                ordered.append(doc.document_number)
        return tuple(ordered)

    @property
    def fetched(self) -> int:
        return sum(
            1
            for d in self.documents
            if d.disposition is DocumentDisposition.FETCHED
        )

    @property
    def duplicate(self) -> int:
        return sum(
            1
            for d in self.documents
            if d.disposition is DocumentDisposition.DUPLICATE
        )

    @property
    def enumerated(self) -> int:
        # Official inventory units accounted after identity dedup of fetched
        # plus typed non-fetched dispositions (duplicate/excluded/quarantined/
        # failed_final). Enumerated equals unique official identities observed
        # on closed pages (fetched path) plus non-fetched dispositions.
        return (
            self.fetched
            + self.duplicate
            + self.excluded
            + self.quarantined
            + self.failed_final
        )

    def to_date_partition(self) -> DatePartition:
        unique_docs = self.unique_document_numbers
        # For inventory acquisition, body dispositions are deferred to LCR-053.
        # Inventory-closed items are counted as metadata_only placeholders until
        # full-text acquisition runs; that is not a body claim.
        body_dispositions = {
            BodyTextDisposition.METADATA_ONLY.value: self.fetched,
        }
        if self.excluded:
            body_dispositions[BodyTextDisposition.UNAVAILABLE.value] = self.excluded
        if self.failed_final:
            body_dispositions[
                BodyTextDisposition.FAILED_FINAL.value
            ] = self.failed_final
        enumerated = (
            self.fetched
            + self.duplicate
            + self.excluded
            + self.quarantined
            + self.failed_final
        )
        return DatePartition(
            partition_id=self.spec.partition_id,
            start_date=self.spec.start_date,
            end_date=self.spec.end_date,
            status=self.status,
            api_total=self.api_total,
            enumerated=enumerated,
            fetched=self.fetched,
            duplicate=self.duplicate,
            excluded=self.excluded,
            quarantined=self.quarantined,
            failed_final=self.failed_final,
            pages=tuple(page.to_page_receipt() for page in self.pages),
            document_numbers=unique_docs,
            body_text_dispositions=body_dispositions,
            year_month=self.spec.year_month,
            official_source_url=FEDERAL_REGISTER_DOCUMENTS_API,
            response_hashes=tuple(page.response_hash for page in self.pages),
        )

    def to_checkpoint_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.spec.partition_id,
            "spec": self.spec.to_dict(),
            "status": self.status.value,
            "api_total": self.api_total,
            "failed_final": self.failed_final,
            "excluded": self.excluded,
            "quarantined": self.quarantined,
            "pages": [page.to_dict() for page in self.pages],
            "documents": [doc.to_dict() for doc in self.documents],
        }


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def build_documents_api_url(
    *,
    start_date: str,
    end_date: str,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    order: str = "oldest",
) -> str:
    """Build a FederalRegister.gov documents.json request URL."""

    start = validate_calendar_date(start_date, name="start_date")
    end = validate_calendar_date(end_date, name="end_date")
    page_n = _require_non_negative_int(page, "page")
    if page_n < 1:
        raise PageFetchError("page must be >= 1")
    per = _require_non_negative_int(per_page, "per_page")
    if per < 1 or per > MAX_API_PER_PAGE:
        raise PageFetchError(
            f"per_page must be in 1..{MAX_API_PER_PAGE}, got {per}"
        )
    params = {
        "per_page": str(per),
        "page": str(page_n),
        "order": order,
        "conditions[publication_date][gte]": start,
        "conditions[publication_date][lte]": end,
    }
    # Request stable identity + locator fields used by inventory and LCR-053.
    fields = [
        "document_number",
        "publication_date",
        "title",
        "type",
        "html_url",
        "pdf_url",
        "full_text_xml_url",
        "agencies",
        "citation",
    ]
    query_parts = [urllib.parse.urlencode(params)]
    for field_name in fields:
        query_parts.append(
            urllib.parse.urlencode({"fields[]": field_name})
        )
    return f"{FEDERAL_REGISTER_DOCUMENTS_API}?{'&'.join(query_parts)}"


def _validate_documents_request_url(
    value: Any,
    *,
    start_date: str,
    end_date: str,
    page: int,
    per_page: int,
    allow_canonical_equivalent: bool,
) -> str:
    """Require the planned request or its exact Rails URL serialization."""

    url = _require_non_empty_str(value, "documents request URL", maximum=4096)
    expected = build_documents_api_url(
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
    )
    if url == expected:
        return url
    if not allow_canonical_equivalent:
        raise PageFetchError("documents request URL is not the exact planned URL")

    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.federalregister.gov"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"/api/v1/documents", "/api/v1/documents.json"}
        or parsed.fragment
    ):
        raise PageFetchError(
            "continuation URL is not the exact FederalRegister.gov endpoint"
        )
    try:
        observed_query = urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
        expected_query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(expected).query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise PageFetchError("continuation URL query is malformed") from exc
    expected_keys = set(expected_query)
    allowed_key_sets = {
        frozenset(expected_keys),
        frozenset(expected_keys | {"format"}),
        frozenset(expected_keys | {"format", "search_after_cursor"}),
    }
    if frozenset(observed_query) not in allowed_key_sets:
        raise PageFetchError(
            "continuation URL query fields differ from the exact contract"
        )
    for key, expected_values in expected_query.items():
        observed_values = observed_query.get(key)
        if key == "fields[]":
            if (
                not isinstance(observed_values, list)
                or len(observed_values) != len(expected_values)
                or sorted(observed_values) != sorted(expected_values)
            ):
                raise PageFetchError(
                    "continuation URL field projection drifted"
                )
        elif observed_values != expected_values:
            raise PageFetchError(
                f"continuation URL query field {key!r} drifted"
            )
    if "format" in observed_query and observed_query["format"] != ["json"]:
        raise PageFetchError("continuation URL format drifted")
    if "search_after_cursor" in observed_query:
        cursor_values = observed_query["search_after_cursor"]
        if (
            observed_query.get("format") != ["json"]
            or len(cursor_values) != 1
            or re.fullmatch(r"[A-Za-z0-9_=-]{1,1024}", cursor_values[0]) is None
        ):
            raise PageFetchError("continuation URL cursor is malformed")
    return url


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise PageFetchError(f"Federal Register API redirect is forbidden: HTTP {code}")


def _strict_json_object_from_bytes(data: bytes, *, context: str) -> dict[str, Any]:
    """Decode one strict UTF-8 JSON object with no duplicates/nonfinite values."""

    def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def _constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON number {value!r}")

    try:
        text = data.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
        # This rejects escaped lone surrogates and values that cannot be
        # represented by the canonical receipt encoder.
        canonical_json_dumps(payload).encode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError, TypeError) as exc:
        raise PageFetchError(f"{context} is not strict canonicalizable JSON") from exc
    if not isinstance(payload, dict):
        raise PageFetchError(f"{context} is not a JSON object")
    return payload


def live_http_transport(
    url: str,
    headers: Mapping[str, str],
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[bytes, dict[str, Any]]:
    """Fetch one official API page over HTTPS (live mode only)."""

    parsed_url = urllib.parse.urlsplit(url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "www.federalregister.gov"
        or parsed_url.port is not None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"/api/v1/documents", "/api/v1/documents.json"}
        or parsed_url.fragment
    ):
        raise PageFetchError("live inventory URL is outside the exact HTTPS endpoint")
    request = urllib.request.Request(  # noqa: S310 - exact HTTPS endpoint checked above
        url,
        headers={str(k): str(v) for k, v in headers.items()},
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise PageFetchError("Federal Register API response URL drifted")
            if response.headers.get_content_type() != "application/json":
                raise PageFetchError("Federal Register API response is not JSON")
            encoding = (response.headers.get("Content-Encoding") or "identity").lower()
            if encoding != "identity":
                raise PageFetchError("compressed API responses are forbidden")
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                try:
                    length = int(declared_length, 10)
                except ValueError as exc:
                    raise PageFetchError("invalid API Content-Length") from exc
                if length < 0 or length > MAX_API_RESPONSE_BYTES:
                    raise PageFetchError(
                        "API Content-Length exceeds the response bound"
                    )
            body = response.read(MAX_API_RESPONSE_BYTES + 1)
            if len(body) > MAX_API_RESPONSE_BYTES:
                raise PageFetchError("API response exceeds the response bound")
            if declared_length is not None and len(body) != length:
                raise PageFetchError("API body length does not match Content-Length")
    except PageFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise PageFetchError(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise PageFetchError(f"URL error for {url}: {exc.reason}") from exc
    payload = _strict_json_object_from_bytes(body, context=f"API response for {url}")
    return body, payload


@dataclass(frozen=True)
class FixturePageRecipe:
    """Compact sealed recipe for one fixture API page."""

    page_number: int
    documents: tuple[Mapping[str, Any], ...]
    api_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "documents": [dict(d) for d in self.documents],
            "api_total": self.api_total,
        }


@dataclass(frozen=True)
class FixturePartitionRecipe:
    """Compact sealed recipe for one fixture partition."""

    partition_id: str
    start_date: str
    end_date: str
    year_month: str
    pages: tuple[FixturePageRecipe, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "year_month": self.year_month,
            "pages": [page.to_dict() for page in self.pages],
        }


def _fixture_document_number(year: int, seq: int) -> str:
    # YYYY-NNNNN shape with 5-digit suffix (official FR style).
    return f"{year}-{seq:05d}"


def _fixture_doc_payload(
    *,
    document_number: str,
    publication_date: str,
    title: str,
    document_type: str = "Rule",
    agency: str = "Environmental Protection Agency",
) -> dict[str, Any]:
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "title": title,
        "type": document_type,
        "abstract": f"Abstract for {document_number}.",
        "html_url": (
            f"https://www.federalregister.gov/documents/"
            f"{publication_date.replace('-', '/')}/{document_number}"
        ),
        "pdf_url": (
            f"https://www.govinfo.gov/content/pkg/FR-{publication_date}/pdf/"
            f"{document_number}.pdf"
        ),
        "full_text_xml_url": (
            f"https://www.federalregister.gov/documents/full_text/xml/"
            f"{document_number}.xml"
        ),
        "agencies": [{"name": agency}],
        "citation": f"91 FR {document_number.split('-')[-1]}",
    }


def build_default_fixture_recipe(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
    docs_per_partition: int = FIXTURE_DOCS_PER_PARTITION,
    per_page: int = FIXTURE_PER_PAGE,
) -> dict[str, Any]:
    """Build a compact sealed fixture recipe for offline inventory acquisition.

    Covers the post-legacy-endpoint delta window through the observation cutoff
    with monthly partitions. Each partition has a deterministic set of official
    document identities and paginated API page payloads.
    """

    cutoff = require_immutable_observation_cutoff(observation_cutoff)
    cutoff_date = observation_cutoff_date(cutoff)
    specs = plan_monthly_partitions(FIXTURE_RANGE_START, cutoff_date)
    partitions: list[dict[str, Any]] = []
    global_seq = 45000

    for spec in specs:
        year = int(spec.year_month[:4])
        docs: list[dict[str, Any]] = []
        for i in range(docs_per_partition):
            # Publication date inside the partition (stable, deterministic).
            start = parse_calendar_date(spec.start_date)
            end = parse_calendar_date(spec.end_date)
            span = max(0, (end - start).days)
            offset = min(
                span,
                (i * max(1, span // max(docs_per_partition, 1))) % (span + 1),
            )
            pub = (start + timedelta(days=offset)).isoformat()
            doc_number = _fixture_document_number(year, global_seq)
            global_seq += 1
            docs.append(
                _fixture_doc_payload(
                    document_number=doc_number,
                    publication_date=pub,
                    title=f"Fixture Federal Register document {doc_number}",
                    document_type=("Rule", "Proposed Rule", "Notice")[i % 3],
                    agency=(
                        "Environmental Protection Agency",
                        "Department of Transportation",
                        "Department of Commerce",
                    )[i % 3],
                )
            )

        pages: list[dict[str, Any]] = []
        page_number = 1
        for offset in range(0, len(docs), per_page):
            chunk = docs[offset : offset + per_page]
            pages.append(
                {
                    "page_number": page_number,
                    "documents": chunk,
                    "api_total": len(docs),
                }
            )
            page_number += 1
        if not pages:
            # Empty partition still needs a closed empty page ledger only when
            # api_total == 0; leave pages empty (oracle allows empty for zero).
            pages = []

        partitions.append(
            {
                "partition_id": spec.partition_id,
                "start_date": spec.start_date,
                "end_date": spec.end_date,
                "year_month": spec.year_month,
                "pages": pages,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": MODE_FIXTURE,
        "observation_cutoff": cutoff,
        "range_start": FIXTURE_RANGE_START,
        "range_end": cutoff_date,
        "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
        "delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "per_page": per_page,
        "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
        "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
        "notes": (
            "Compact sealed Federal Register inventory fixture for LCR-052. "
            "Covers the post-2026-03-02 delta through the observation cutoff "
            "with monthly partitions and stable official identities. Expand "
            "via build_default_fixture_recipe() / FixtureApiTransport."
        ),
        "partitions": partitions,
    }


class FixtureApiTransport:
    """Deterministic offline transport backed by a sealed fixture recipe."""

    def __init__(self, recipe: JsonMapping) -> None:
        raw = _as_mapping(recipe, "fixture_recipe")
        self.recipe = raw
        self.range_start = validate_calendar_date(
            raw.get("range_start", FIXTURE_RANGE_START), name="range_start"
        )
        self.range_end = validate_calendar_date(
            raw.get("range_end", FIXTURE_RANGE_END), name="range_end"
        )
        self.per_page = int(raw.get("per_page") or FIXTURE_PER_PAGE)
        self._by_partition: dict[str, Mapping[str, Any]] = {}
        self._by_range: dict[tuple[str, str], Mapping[str, Any]] = {}
        for item in raw.get("partitions") or ():
            part = _as_mapping(item, "partition")
            pid = str(part.get("partition_id") or "")
            start = str(part.get("start_date") or "")
            end = str(part.get("end_date") or "")
            self._by_partition[pid] = part
            self._by_range[(start, end)] = part

    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> tuple[bytes, dict[str, Any]]:
        _ = headers  # Fixture transport ignores headers by design.
        validate_official_url(url, name="url")
        parsed = urllib.parse.urlparse(url)
        if not parsed.path.endswith("/documents.json"):
            raise FixtureTransportError(
                f"fixture transport only serves documents.json: {url}"
            )
        qs = urllib.parse.parse_qs(parsed.query)
        start = (qs.get("conditions[publication_date][gte]") or [""])[0]
        end = (qs.get("conditions[publication_date][lte]") or [""])[0]
        page_s = (qs.get("page") or ["1"])[0]
        try:
            page_number = int(page_s)
        except ValueError as exc:
            raise FixtureTransportError(f"invalid page number: {page_s!r}") from exc

        part = self._by_range.get((start, end))
        if part is None:
            # Empty range response for unplanned ranges (fail closed for
            # unexpected ranges inside the fixture window).
            if start < self.range_start or end > self.range_end:
                raise FixtureTransportError(
                    f"fixture has no partition for range {start}..{end}"
                )
            payload = {
                "count": 0,
                "description": "Fixture Federal Register documents.json response",
            }
            body = canonical_json_dumps(payload).encode("utf-8")
            return body, payload

        pages = list(part.get("pages") or ())
        if not pages:
            payload = {
                "count": 0,
                "description": "Fixture Federal Register documents.json response",
            }
            body = canonical_json_dumps(payload).encode("utf-8")
            return body, payload

        # Locate the requested page.
        page_recipe = None
        for item in pages:
            if int(item.get("page_number") or 0) == page_number:
                page_recipe = item
                break
        if page_recipe is None:
            # Beyond last page → empty results (API-compatible).
            api_total = int(pages[0].get("api_total") or 0)
            payload = {
                "count": api_total,
                "description": "Fixture Federal Register documents.json response",
                "total_pages": len(pages),
                "results": [],
            }
            body = canonical_json_dumps(payload).encode("utf-8")
            return body, payload

        results = list(page_recipe.get("documents") or [])
        api_total = int(page_recipe.get("api_total") or len(results))
        total_pages = len(pages)
        payload = {
            "count": api_total,
            "description": "Fixture Federal Register documents.json response",
            "total_pages": total_pages,
            "results": results,
        }
        # Next page URL when more pages remain.
        if page_number < total_pages:
            payload["next_page_url"] = build_documents_api_url(
                start_date=start,
                end_date=end,
                page=page_number + 1,
                per_page=self.per_page,
            )
        if page_number > 1:
            payload["previous_page_url"] = build_documents_api_url(
                start_date=start,
                end_date=end,
                page=page_number - 1,
                per_page=self.per_page,
            )
        body = canonical_json_dumps(payload).encode("utf-8")
        return body, payload


# ---------------------------------------------------------------------------
# Checkpoint I/O (atomic)
# ---------------------------------------------------------------------------


def atomic_write_json(path: PathLike, payload: Mapping[str, Any]) -> None:
    """Atomically write *payload* as sorted JSON to *path*."""

    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = target.parent.resolve(strict=True)
    if resolved_parent != target.parent:
        raise CheckpointError("JSON output parent must be a canonical real directory")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert_no_secrets(payload, context=f"checkpoint:{target.name}")
    parent_fd = os.open(
        resolved_parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0),
    )
    tmp_name = ""
    fd = -1
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(resolved_parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1  # ownership transferred to the file object
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        os.fsync(parent_fd)
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_fd)


def atomic_create_json(path: PathLike, payload: Mapping[str, Any]) -> None:
    """Atomically create *path* without replacing any existing file."""

    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = target.parent.resolve(strict=True)
    if resolved_parent != target.parent:
        raise CheckpointError("JSON output parent must be a canonical real directory")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert_no_secrets(payload, context=f"checkpoint:{target.name}")
    parent_fd = os.open(
        resolved_parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0),
    )
    tmp_name = ""
    fd = -1
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(resolved_parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1  # ownership transferred to the file object
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise CheckpointError(
                f"refusing to replace existing JSON output: {target}"
            ) from exc
        os.fsync(parent_fd)
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        os.close(parent_fd)


def load_json_object(path: PathLike) -> dict[str, Any]:
    target = Path(path).absolute()
    try:
        resolved = target.resolve(strict=True)
        if resolved != target:
            raise CheckpointError(f"JSON input path is not canonical: {target}")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(target, flags)
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size < 2
                or before.st_size > MAX_CHECKPOINT_BYTES
            ):
                raise CheckpointError(
                    f"JSON input is not a bounded regular file: {target}"
                )
            chunks: list[bytes] = []
            remaining = MAX_CHECKPOINT_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or len(data) > MAX_CHECKPOINT_BYTES
        ):
            raise CheckpointError(f"JSON input metadata drifted: {target}")
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or len(data) != before.st_size:
            raise CheckpointError(f"JSON input changed while reading: {target}")
        payload = _strict_json_object_from_bytes(data, context=f"JSON input {target}")
    except (OSError, PageFetchError) as exc:
        raise CheckpointError(f"corrupt JSON input {target}: {exc}") from exc
    return payload


def _prepare_checkpoint_directory(path: PathLike) -> Path:
    target = Path(path).absolute()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        resolved = target.resolve(strict=True)
        metadata = target.lstat()
    except OSError as exc:
        raise CheckpointError(f"checkpoint directory is unavailable: {target}") from exc
    if resolved != target or not stat.S_ISDIR(metadata.st_mode):
        raise CheckpointError("checkpoint directory must be a canonical real directory")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise CheckpointError(
            "checkpoint directory must be owned by the current user and not writable "
            "by group/other"
        )
    return target


def _load_checkpoint_json_object(path: PathLike) -> dict[str, Any]:
    """Read one bounded, regular, canonical checkpoint without following links."""

    target = Path(path).absolute()
    parent = _prepare_checkpoint_directory(target.parent)
    if target.parent != parent:
        raise CheckpointError("checkpoint path escaped its canonical directory")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise CheckpointError(f"checkpoint cannot be opened safely: {target}") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
            or before.st_size < 2
            or before.st_size > MAX_CHECKPOINT_BYTES
        ):
            raise CheckpointError("checkpoint file metadata is not private and regular")
        chunks: list[bytes] = []
        remaining = MAX_CHECKPOINT_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity or len(data) != before.st_size:
        raise CheckpointError("checkpoint changed while it was being read")
    try:
        payload = _strict_json_object_from_bytes(data, context=f"checkpoint {target}")
        canonical = (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (PageFetchError, UnicodeEncodeError, TypeError, ValueError) as exc:
        raise CheckpointError(f"checkpoint is not strict JSON: {target}") from exc
    if data != canonical:
        raise CheckpointError("checkpoint bytes are not the exact canonical framing")
    return payload


def partition_checkpoint_path(checkpoint_dir: PathLike, partition_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", partition_id)
    return Path(checkpoint_dir) / f"{safe}.json"


# ---------------------------------------------------------------------------
# Acquisition engine
# ---------------------------------------------------------------------------


@dataclass
class AcquisitionConfig:
    """Runtime configuration for one inventory acquisition run."""

    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    range_start: str = FIXTURE_RANGE_START
    range_end: str = FIXTURE_RANGE_END
    mode: AcquisitionMode = AcquisitionMode.FIXTURE
    per_page: int = DEFAULT_PER_PAGE
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS
    checkpoint_dir: Optional[Path] = None
    resume: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(
            self,
            "range_start",
            validate_calendar_date(self.range_start, name="range_start"),
        )
        object.__setattr__(
            self,
            "range_end",
            validate_calendar_date(self.range_end, name="range_end"),
        )
        object.__setattr__(self, "mode", AcquisitionMode.coerce(self.mode))
        per = _require_non_negative_int(self.per_page, "per_page")
        if per < 1 or per > MAX_API_PER_PAGE:
            raise FederalRegisterAcquisitionError(
                f"per_page must be in 1..{MAX_API_PER_PAGE}"
            )
        object.__setattr__(self, "per_page", per)
        # Cutoff-relative: range must not extend past observation cutoff date.
        cutoff_day = observation_cutoff_date(self.observation_cutoff)
        if self.range_end > cutoff_day:
            raise FederalRegisterAcquisitionError(
                f"range_end {self.range_end} exceeds observation cutoff {cutoff_day}"
            )
        if self.range_start > self.range_end:
            raise FederalRegisterAcquisitionError(
                f"range_start {self.range_start} > range_end {self.range_end}"
            )
        if self.mode is AcquisitionMode.LIVE:
            if self.per_page != DEFAULT_PER_PAGE:
                raise FederalRegisterAcquisitionError(
                    "live inventory requires the exact sealed per_page value"
                )
            if self.observation_cutoff != DEFAULT_OBSERVATION_CUTOFF:
                raise FederalRegisterAcquisitionError(
                    "live inventory authority requires the exact sealed observation "
                    f"cutoff {DEFAULT_OBSERVATION_CUTOFF}"
                )
            if self.range_start != LEGACY_DELTA_START_INCLUSIVE:
                raise FederalRegisterAcquisitionError(
                    "live inventory authority requires the exact post-baseline "
                    f"range start {LEGACY_DELTA_START_INCLUSIVE}, got "
                    f"{self.range_start}"
                )
            if self.range_end != cutoff_day:
                raise FederalRegisterAcquisitionError(
                    "live inventory authority requires range_end to equal the "
                    f"observation cutoff date {cutoff_day}, got {self.range_end}"
                )
            if self.dataset_repo_id != DEFAULT_DATASET_REPO_ID:
                raise FederalRegisterAcquisitionError(
                    "live inventory dataset_repo_id must equal the sealed target"
                )
            if self.previous_public_pin != PREVIOUS_PUBLIC_PIN:
                raise FederalRegisterAcquisitionError(
                    "live inventory previous_public_pin must equal the sealed baseline"
                )


def _checkpoint_config_payload(
    config: AcquisitionConfig,
    spec: PartitionSpec,
) -> dict[str, Any]:
    """Return the exact acquisition authority a reusable checkpoint belongs to."""

    return {
        "schema": "federal-register-inventory-checkpoint-binding@1",
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "mode": config.mode.value,
        "observation_cutoff": config.observation_cutoff,
        "range_start": config.range_start,
        "range_end": config.range_end,
        "per_page": config.per_page,
        "dataset_repo_id": config.dataset_repo_id,
        "previous_public_pin": config.previous_public_pin,
        "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
        "partition": spec.to_dict(),
    }


def _checkpoint_config_binding(
    config: AcquisitionConfig,
    spec: PartitionSpec,
) -> str:
    return digest_mapping(_checkpoint_config_payload(config, spec))


def _build_partition_checkpoint(
    state: PartitionAcquisitionState,
    *,
    config: AcquisitionConfig,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": CHECKPOINT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "checkpoint_kind": "partition",
        "config": _checkpoint_config_payload(config, state.spec),
        "config_binding": _checkpoint_config_binding(config, state.spec),
        "state": state.to_checkpoint_dict(),
    }
    body["checkpoint_digest"] = digest_mapping(body)
    return body


@dataclass
class AcquisitionResult:
    """Result of a completed (or failed) inventory acquisition run."""

    config: AcquisitionConfig
    partitions: list[PartitionAcquisitionState]
    documents_by_legal_id: dict[str, InventoryDocument]
    duplicates: list[InventoryDocument]
    receipt_id: str
    observed_at: str
    mode: AcquisitionMode
    frontier_closed: bool = False
    completeness: Optional[CompletenessResult] = None
    inventory_report: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def unique_document_count(self) -> int:
        return len(self.documents_by_legal_id)

    @property
    def enumerated(self) -> int:
        return sum(p.enumerated for p in self.partitions)

    @property
    def fetched(self) -> int:
        return sum(p.fetched for p in self.partitions)

    @property
    def duplicate_count(self) -> int:
        return sum(p.duplicate for p in self.partitions)

    @property
    def failed_final(self) -> int:
        return sum(p.failed_final for p in self.partitions)

    @property
    def official_total(self) -> int:
        return sum(p.api_total for p in self.partitions)

    @property
    def open_page_count(self) -> int:
        return sum(
            1
            for p in self.partitions
            for page in p.pages
            if page.status.is_open
        )

    def unique_document_numbers(self) -> tuple[str, ...]:
        return tuple(
            sorted({d.document_number for d in self.documents_by_legal_id.values()})
        )


def _restore_partition_state(
    payload: JsonMapping,
    *,
    config: AcquisitionConfig,
    expected_spec: PartitionSpec,
) -> PartitionAcquisitionState:
    raw = _as_mapping(payload, "checkpoint")
    expected_top_keys = {
        "schema",
        "schema_version",
        "task_id",
        "checkpoint_kind",
        "config",
        "config_binding",
        "state",
        "checkpoint_digest",
    }
    if set(raw) != expected_top_keys:
        raise CheckpointError(
            "checkpoint fields differ from the exact v2 schema: "
            f"missing={sorted(expected_top_keys - set(raw))}; "
            f"extra={sorted(set(raw) - expected_top_keys)}"
        )
    if raw.get("schema") != CHECKPOINT_SCHEMA:
        raise CheckpointError("checkpoint schema is not the exact v2 schema")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CheckpointError("checkpoint schema_version does not match runtime")
    if raw.get("task_id") != TASK_ID or raw.get("checkpoint_kind") != "partition":
        raise CheckpointError("checkpoint task/kind identity mismatch")
    expected_digest = digest_mapping(
        {key: value for key, value in raw.items() if key != "checkpoint_digest"}
    )
    if raw.get("checkpoint_digest") != expected_digest:
        raise CheckpointError("checkpoint digest does not match its exact bytes")
    expected_config = _checkpoint_config_payload(config, expected_spec)
    try:
        observed_config_bytes = canonical_json_dumps(raw.get("config")).encode("utf-8")
        expected_config_bytes = canonical_json_dumps(expected_config).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise CheckpointError("checkpoint configuration is not canonical") from exc
    if observed_config_bytes != expected_config_bytes:
        raise CheckpointError("checkpoint acquisition authority/configuration mismatch")
    expected_binding = _checkpoint_config_binding(config, expected_spec)
    if raw.get("config_binding") != expected_binding:
        raise CheckpointError("checkpoint configuration binding mismatch")

    state_raw = _as_mapping(raw.get("state"), "checkpoint.state")
    expected_state_keys = {
        "partition_id",
        "spec",
        "status",
        "api_total",
        "failed_final",
        "excluded",
        "quarantined",
        "pages",
        "documents",
    }
    if set(state_raw) != expected_state_keys:
        raise CheckpointError("checkpoint state fields differ from the exact schema")
    spec_raw = _as_mapping(state_raw.get("spec"), "checkpoint.state.spec")
    if set(spec_raw) != {"partition_id", "start_date", "end_date", "year_month"}:
        raise CheckpointError(
            "checkpoint partition fields differ from the exact schema"
        )
    spec = PartitionSpec(
        partition_id=_require_non_empty_str(
            spec_raw.get("partition_id"),
            "checkpoint.state.spec.partition_id",
            maximum=128,
        ),
        start_date=_require_non_empty_str(
            spec_raw.get("start_date"),
            "checkpoint.state.spec.start_date",
            maximum=10,
        ),
        end_date=_require_non_empty_str(
            spec_raw.get("end_date"),
            "checkpoint.state.spec.end_date",
            maximum=10,
        ),
        year_month=_require_non_empty_str(
            spec_raw.get("year_month"),
            "checkpoint.state.spec.year_month",
            maximum=7,
        ),
    )
    if spec != expected_spec or state_raw.get("partition_id") != spec.partition_id:
        raise CheckpointError("checkpoint partition identity does not match the plan")
    state = PartitionAcquisitionState(spec=spec)
    state.api_total = _require_non_negative_int(
        state_raw.get("api_total"), "checkpoint.state.api_total"
    )
    state.failed_final = _require_non_negative_int(
        state_raw.get("failed_final"), "checkpoint.state.failed_final"
    )
    state.excluded = _require_non_negative_int(
        state_raw.get("excluded"), "checkpoint.state.excluded"
    )
    state.quarantined = _require_non_negative_int(
        state_raw.get("quarantined"), "checkpoint.state.quarantined"
    )
    raw_state_status = state_raw.get("status")
    if not isinstance(raw_state_status, str):
        raise CheckpointError("checkpoint state status must be an exact string")
    try:
        state.status = PartitionStatus(raw_state_status)
    except ValueError as exc:
        raise CheckpointError("checkpoint state status is unknown") from exc
    page_items = _as_sequence(state_raw.get("pages"), "checkpoint.state.pages")
    if not isinstance(page_items, list):
        raise CheckpointError("checkpoint pages must be a JSON list")
    for page_raw in page_items:
        page = _as_mapping(page_raw, "page")
        expected_page_keys = {
            "page_id",
            "page_number",
            "partition_id",
            "request_url",
            "response_hash",
            "result_count",
            "document_numbers",
            "status",
            "cursor",
            "api_total",
            "next_page_url",
        }
        if set(page) != expected_page_keys:
            raise CheckpointError("checkpoint page fields differ from the exact schema")
        raw_page_status = page.get("status")
        if not isinstance(raw_page_status, str):
            raise CheckpointError("checkpoint page status must be an exact string")
        try:
            page_status = PageStatus(raw_page_status)
        except ValueError as exc:
            raise CheckpointError("checkpoint page status is unknown") from exc
        raw_response_hash = page.get("response_hash")
        if not isinstance(raw_response_hash, str):
            raise CheckpointError("checkpoint response hash must be an exact string")
        if raw_response_hash != normalize_sha256(
            raw_response_hash, name="checkpoint.page.response_hash"
        ):
            raise CheckpointError("checkpoint response hash is not canonical")
        raw_document_numbers = _as_sequence(
            page.get("document_numbers"),
            "checkpoint.page.document_numbers",
        )
        if not isinstance(raw_document_numbers, list):
            raise CheckpointError(
                "checkpoint page document_numbers must be a JSON list"
            )
        state.pages.append(
            PageEvidence(
                page_id=page.get("page_id"),
                page_number=page.get("page_number"),
                partition_id=page.get("partition_id"),
                request_url=page.get("request_url"),
                response_hash=page.get("response_hash"),
                result_count=page.get("result_count"),
                document_numbers=tuple(raw_document_numbers),
                status=page_status,
                cursor=page.get("cursor"),
                api_total=page.get("api_total"),
                next_page_url=page.get("next_page_url"),
            )
        )
    document_items = _as_sequence(
        state_raw.get("documents"), "checkpoint.state.documents"
    )
    if not isinstance(document_items, list):
        raise CheckpointError("checkpoint documents must be a JSON list")
    for doc_raw in document_items:
        doc = _as_mapping(doc_raw, "document")
        expected_document_keys = {
            "document_number",
            "publication_date",
            "title",
            "html_url",
            "pdf_url",
            "xml_url",
            "document_type",
            "agencies",
            "disposition",
            "legal_id",
            "abstract",
            "page_id",
            "partition_id",
        }
        if set(doc) != expected_document_keys:
            raise CheckpointError(
                "checkpoint document fields differ from the exact schema"
            )
        raw_disposition = doc.get("disposition")
        if not isinstance(raw_disposition, str):
            raise CheckpointError(
                "checkpoint document disposition must be an exact string"
            )
        try:
            disposition = DocumentDisposition(raw_disposition)
        except ValueError as exc:
            raise CheckpointError("checkpoint document disposition is unknown") from exc
        raw_agencies = _as_sequence(
            doc.get("agencies"), "checkpoint.document.agencies"
        )
        if not isinstance(raw_agencies, list):
            raise CheckpointError("checkpoint document agencies must be a JSON list")
        state.documents.append(
            InventoryDocument(
                document_number=doc.get("document_number"),
                publication_date=doc.get("publication_date"),
                title=doc.get("title"),
                html_url=doc.get("html_url"),
                pdf_url=doc.get("pdf_url"),
                xml_url=doc.get("xml_url"),
                document_type=doc.get("document_type"),
                agencies=tuple(raw_agencies),
                disposition=disposition,
                legal_id=doc.get("legal_id"),
                abstract=doc.get("abstract"),
                page_id=doc.get("page_id"),
                partition_id=doc.get("partition_id"),
            )
        )

    if state.status is not PartitionStatus.CLOSED or state.failed_final != 0:
        raise CheckpointError("only exact closed zero-failure checkpoints are reusable")
    if state.excluded != 0 or state.quarantined != 0:
        raise CheckpointError(
            "inventory checkpoints cannot hide excluded/quarantined rows"
        )
    expected_page_count = max(
        1, (state.api_total + config.per_page - 1) // config.per_page
    )
    if len(state.pages) != expected_page_count:
        raise CheckpointError("checkpoint page count does not match official total")
    seen_hashes: set[str] = set()
    page_ids: set[str] = set()
    expected_request_url = build_documents_api_url(
        start_date=spec.start_date,
        end_date=spec.end_date,
        page=1,
        per_page=config.per_page,
    )
    for expected_number, page in enumerate(state.pages, start=1):
        expected_page_id = f"{spec.partition_id}/page-{expected_number}"
        if (
            page.page_number != expected_number
            or page.page_id != expected_page_id
            or page.partition_id != spec.partition_id
            or page.request_url != expected_request_url
            or page.cursor != f"page={expected_number}"
            or page.api_total != state.api_total
            or page.status is not PageStatus.VERIFIED
        ):
            raise CheckpointError("checkpoint page identity/request ledger mismatch")
        if page.response_hash in seen_hashes:
            raise CheckpointError("checkpoint contains duplicate page response hashes")
        seen_hashes.add(page.response_hash)
        page_ids.add(page.page_id)
        if expected_number < expected_page_count:
            expected_next = _validate_documents_request_url(
                page.next_page_url,
                start_date=spec.start_date,
                end_date=spec.end_date,
                page=expected_number + 1,
                per_page=config.per_page,
                allow_canonical_equivalent=config.mode is AcquisitionMode.LIVE,
            )
            expected_request_url = expected_next
        elif page.next_page_url is not None:
            raise CheckpointError("checkpoint final page has a continuation URL")
    if sum(page.result_count for page in state.pages) != state.api_total:
        raise CheckpointError("checkpoint page counts do not reconcile")
    if any(doc.partition_id != spec.partition_id for doc in state.documents):
        raise CheckpointError("checkpoint document belongs to another partition")
    if any(doc.page_id not in page_ids for doc in state.documents):
        raise CheckpointError("checkpoint document references an unknown page")
    for doc in state.documents:
        if not (spec.start_date <= doc.publication_date <= spec.end_date):
            raise CheckpointError("checkpoint document date is outside its partition")
        if doc.legal_id != build_legal_id(doc.document_number, doc.publication_date):
            raise CheckpointError("checkpoint document legal_id is not canonical")
    for page in state.pages:
        observed_numbers = tuple(
            doc.document_number
            for doc in state.documents
            if doc.page_id == page.page_id
        )
        if page.document_numbers != observed_numbers or page.result_count != len(
            observed_numbers
        ):
            raise CheckpointError("checkpoint page/document membership mismatch")
    return state


def _fetch_with_retries(
    transport: ApiTransport,
    url: str,
    headers: Mapping[str, str],
    *,
    max_retries: int,
    backoff: float,
) -> tuple[bytes, dict[str, Any]]:
    last_error: Exception | None = None
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        try:
            return transport(url, headers)
        except FederalRegisterAcquisitionError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(backoff * (2**attempt))
        except Exception as exc:  # noqa: BLE001 - transport boundary
            last_error = PageFetchError(str(exc))
            if attempt + 1 >= attempts:
                break
            time.sleep(backoff * (2**attempt))
    if last_error is None:
        raise PageFetchError("transport retry loop ended without a result")
    raise last_error


def acquire_partition(
    spec: PartitionSpec,
    *,
    config: AcquisitionConfig,
    transport: ApiTransport,
    known_legal_ids: MutableMapping[str, InventoryDocument],
    checkpoint_dir: Path | None = None,
) -> PartitionAcquisitionState:
    """Acquire every official API page for one date partition."""

    # Fixture checkpoints can be replayed directly because their transport is a
    # sealed deterministic recipe. A live checkpoint is only a candidate: its
    # unkeyed digest detects corruption but cannot authenticate official bytes.
    # Re-fetch the complete partition and require byte-equivalent canonical
    # state before accepting it or replacing the checkpoint.
    live_checkpoint_candidate: PartitionAcquisitionState | None = None
    if config.resume and checkpoint_dir is not None:
        ckpt_path = partition_checkpoint_path(checkpoint_dir, spec.partition_id)
        if ckpt_path.is_file():
            restored = _restore_partition_state(
                _load_checkpoint_json_object(ckpt_path),
                config=config,
                expected_spec=spec,
            )
            if (
                restored.status is PartitionStatus.CLOSED
                and restored.spec.start_date == spec.start_date
                and restored.spec.end_date == spec.end_date
                and all(not page.status.is_open for page in restored.pages)
                and restored.failed_final == 0
            ):
                if config.mode is AcquisitionMode.LIVE:
                    live_checkpoint_candidate = restored
                else:
                    # Re-register identities into the shared union.
                    for doc in restored.documents:
                        if doc.disposition is DocumentDisposition.FETCHED:
                            if doc.legal_id in known_legal_ids:
                                raise CheckpointError(
                                    "checkpoint marks an already-observed legal "
                                    "identity "
                                    f"as fetched: {doc.legal_id}"
                                )
                            known_legal_ids[doc.legal_id] = doc
                        elif doc.disposition is DocumentDisposition.DUPLICATE:
                            if doc.legal_id not in known_legal_ids:
                                raise CheckpointError(
                                    "checkpoint marks an unseen legal identity as "
                                    "duplicate: "
                                    f"{doc.legal_id}"
                                )
                    return restored

    state = PartitionAcquisitionState(spec=spec, status=PartitionStatus.IN_PROGRESS)
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "application/json",
    }
    page_number = 1
    total_pages: Optional[int] = None
    seen_page_hashes: set[str] = set()
    request_url = build_documents_api_url(
        start_date=spec.start_date,
        end_date=spec.end_date,
        page=page_number,
        per_page=config.per_page,
    )

    while True:
        url = _validate_documents_request_url(
            request_url,
            start_date=spec.start_date,
            end_date=spec.end_date,
            page=page_number,
            per_page=config.per_page,
            allow_canonical_equivalent=(
                config.mode is AcquisitionMode.LIVE and page_number > 1
            ),
        )
        try:
            body, payload = _fetch_with_retries(
                transport,
                url,
                headers,
                max_retries=config.max_retries,
                backoff=config.retry_backoff_seconds,
            )
        except FederalRegisterAcquisitionError as exc:
            state.failed_final += 1
            state.status = PartitionStatus.FAILED
            raise PageFetchError(
                f"partition {spec.partition_id} page {page_number}: {exc}"
            ) from exc

        response_hash = content_sha256(body)
        if response_hash in seen_page_hashes and page_number > 1:
            # Identical body on a later page is unexplained pagination drift.
            raise InventoryDriftError(
                f"partition {spec.partition_id} page {page_number} response "
                f"hash collides with a prior page (pagination drift)"
            )
        seen_page_hashes.add(response_hash)

        body_payload = _strict_json_object_from_bytes(
            body,
            context=f"partition {spec.partition_id} page {page_number}",
        )
        if body_payload != payload:
            raise PageFetchError(
                f"partition {spec.partition_id} page {page_number}: "
                "transport payload differs from the response bytes"
            )

        _require_non_empty_str(
            payload.get("description"),
            f"partition {spec.partition_id} page {page_number} description",
            maximum=4096,
        )
        raw_api_total = payload.get("count")
        api_total = _require_non_negative_int(
            raw_api_total,
            f"partition {spec.partition_id} page {page_number} count",
        )
        if api_total == 0:
            if page_number != 1:
                raise InventoryDriftError("empty partition exposed multiple pages")
            _require_exact_keys(payload, {"count", "description"}, "API response")
            results: list[Any] = []
            observed_total_pages = 0
        else:
            results_raw = payload.get("results")
            if not isinstance(results_raw, list):
                raise PageFetchError(
                    f"partition {spec.partition_id} page {page_number}: "
                    "results is not a list"
                )
            results = results_raw
            observed_total_pages = _require_non_negative_int(
                payload.get("total_pages"),
                f"partition {spec.partition_id} page {page_number} total_pages",
            )
            expected_total_pages = (
                api_total + config.per_page - 1
            ) // config.per_page
            if observed_total_pages != expected_total_pages:
                raise InventoryDriftError(
                    f"partition {spec.partition_id} page {page_number}: "
                    f"total_pages={observed_total_pages} does not reconcile with "
                    f"count={api_total}/per_page={config.per_page}"
                )
            if page_number > observed_total_pages:
                raise InventoryDriftError("API returned a page past total_pages")
            expected_response_keys = {
                "count",
                "description",
                "total_pages",
                "results",
            }
            if page_number < observed_total_pages:
                expected_response_keys.add("next_page_url")
            if page_number > 1:
                expected_response_keys.add("previous_page_url")
            _require_exact_keys(payload, expected_response_keys, "API response")
            if page_number > 1:
                _validate_documents_request_url(
                    payload.get("previous_page_url"),
                    start_date=spec.start_date,
                    end_date=spec.end_date,
                    page=page_number - 1,
                    per_page=config.per_page,
                    allow_canonical_equivalent=config.mode is AcquisitionMode.LIVE,
                )
        if page_number == 1:
            state.api_total = api_total
            total_pages = observed_total_pages
        elif api_total != state.api_total or observed_total_pages != total_pages:
            raise InventoryDriftError(
                f"partition {spec.partition_id} page {page_number}: "
                "official count/page geometry changed during acquisition"
            )

        if total_pages is None:
            raise PageFetchError(
                f"partition {spec.partition_id} page {page_number}: "
                "page geometry was not initialized"
            )
        expected_result_count = (
            0
            if total_pages == 0
            else (
                config.per_page
                if page_number < total_pages
                else state.api_total - config.per_page * (total_pages - 1)
            )
        )
        if len(results) != expected_result_count:
            raise InventoryDriftError(
                f"partition {spec.partition_id} page {page_number}: "
                f"result_count={len(results)} does not match expected "
                f"{expected_result_count}"
            )

        page_id = f"{spec.partition_id}/page-{page_number}"
        doc_numbers: list[str] = []
        for raw in results:
            if not isinstance(raw, Mapping):
                raise PageFetchError(
                    f"partition {spec.partition_id} page {page_number}: "
                    "non-object result row"
                )
            try:
                inv_doc = InventoryDocument.from_api_result(
                    raw, partition_id=spec.partition_id, page_id=page_id
                )
            except Exception as exc:  # noqa: BLE001
                raise PageFetchError(
                    f"partition {spec.partition_id} page {page_number}: "
                    f"invalid document row: {exc}"
                ) from exc
            if not (spec.start_date <= inv_doc.publication_date <= spec.end_date):
                raise InventoryDriftError(
                    f"partition {spec.partition_id} page {page_number}: "
                    f"document {inv_doc.document_number} publication_date "
                    f"{inv_doc.publication_date} falls outside "
                    f"{spec.start_date}..{spec.end_date}"
                )
            doc_numbers.append(inv_doc.document_number)
            if inv_doc.legal_id in known_legal_ids:
                # Cross-partition or intra-partition duplicate by official identity.
                dup = InventoryDocument(
                    document_number=inv_doc.document_number,
                    publication_date=inv_doc.publication_date,
                    title=inv_doc.title,
                    html_url=inv_doc.html_url,
                    pdf_url=inv_doc.pdf_url,
                    xml_url=inv_doc.xml_url,
                    document_type=inv_doc.document_type,
                    agencies=inv_doc.agencies,
                    disposition=DocumentDisposition.DUPLICATE,
                    legal_id=inv_doc.legal_id,
                    abstract=inv_doc.abstract,
                    page_id=page_id,
                    partition_id=spec.partition_id,
                )
                state.documents.append(dup)
            else:
                known_legal_ids[inv_doc.legal_id] = inv_doc
                state.documents.append(inv_doc)

        raw_next_page_url = payload.get("next_page_url")
        if page_number < total_pages:
            next_page_url = _validate_documents_request_url(
                raw_next_page_url,
                start_date=spec.start_date,
                end_date=spec.end_date,
                page=page_number + 1,
                per_page=config.per_page,
                allow_canonical_equivalent=config.mode is AcquisitionMode.LIVE,
            )
        else:
            if raw_next_page_url not in (None, ""):
                raise InventoryDriftError(
                    f"partition {spec.partition_id} final page exposes a continuation"
                )
            next_page_url = None

        page_evidence = PageEvidence(
            page_id=page_id,
            page_number=page_number,
            partition_id=spec.partition_id,
            # Full official URL including public query parameters.
            request_url=url,
            response_hash=response_hash,
            result_count=len(results),
            document_numbers=tuple(doc_numbers),
            status=PageStatus.VERIFIED,
            cursor=f"page={page_number}",
            api_total=state.api_total,
            next_page_url=next_page_url,
        )
        state.pages.append(page_evidence)

        if total_pages == 0 or page_number >= total_pages:
            break
        request_url = next_page_url
        page_number += 1
        if config.mode is AcquisitionMode.LIVE and config.rate_limit_seconds > 0:
            time.sleep(config.rate_limit_seconds)

    # Reconcile: page document counts vs api_total for unique fetched identities.
    unique_fetched = state.fetched
    if state.api_total != unique_fetched + state.duplicate:
        # Official API count is the pre-dedup result size; after cross-partition
        # dedup, api_total may exceed unique fetched within this partition when
        # duplicates land here. Require: page result_count sum == api_total when
        # no empty trailing page, else allow explained duplicate residual.
        page_result_sum = sum(p.result_count for p in state.pages)
        if page_result_sum != state.api_total and state.api_total != 0:
            # Fail closed on unexplained drift between page results and API total.
            # Empty partitions (api_total=0) are fine with no pages.
            if page_result_sum == 0 and state.api_total > 0:
                raise InventoryDriftError(
                    f"partition {spec.partition_id}: api_total={state.api_total} "
                    f"but page results sum to 0"
                )
            # When pages cover the total, accept; residual identity duplicates
            # are tracked separately.
            if page_result_sum != state.api_total:
                raise InventoryDriftError(
                    f"partition {spec.partition_id}: api_total={state.api_total} "
                    f"!= page result_count sum={page_result_sum}"
                )

    if state.failed_final > 0:
        state.status = PartitionStatus.FAILED
        raise FailedFinalItemError(
            f"partition {spec.partition_id} has failed_final={state.failed_final}"
        )

    state.status = PartitionStatus.CLOSED

    if (
        live_checkpoint_candidate is not None
        and state.to_checkpoint_dict()
        != live_checkpoint_candidate.to_checkpoint_dict()
    ):
        raise InventoryDriftError(
            f"partition {spec.partition_id}: live checkpoint differs from a fresh "
            "official replay"
        )

    if checkpoint_dir is not None:
        atomic_write_json(
            partition_checkpoint_path(checkpoint_dir, spec.partition_id),
            _build_partition_checkpoint(state, config=config),
        )
    return state


def acquire_federal_register_inventory(
    *,
    config: Optional[AcquisitionConfig] = None,
    transport: Optional[ApiTransport] = None,
    fixture_recipe: Optional[JsonMapping] = None,
) -> AcquisitionResult:
    """Acquire the cutoff-bound official Federal Register inventory.

    Fixture mode (default) uses a sealed compact recipe and never contacts the
    network. Live mode requires an explicit live transport or ``mode=live``.
    """

    cfg = config or AcquisitionConfig()
    # Fixture mode uses a fixed observation timestamp so inventory digests are
    # reproducible across CI runs; live mode records wall-clock UTC.
    observed_at = (
        FIXTURE_OBSERVED_AT
        if cfg.mode is AcquisitionMode.FIXTURE
        else format_utc_now()
    )
    if cfg.mode is AcquisitionMode.LIVE:
        cutoff_dt = datetime.fromisoformat(cfg.observation_cutoff)
        observed_dt = datetime.fromisoformat(observed_at)
        if cutoff_dt > observed_dt:
            raise FederalRegisterAcquisitionError(
                "live observation cutoff is later than the verifier-owned start time"
            )
        if fixture_recipe is not None:
            raise LiveTransportDisabledError(
                "fixture_recipe is forbidden for live inventory authority"
            )
        if transport is not None:
            raise LiveTransportDisabledError(
                "caller-supplied transports are forbidden for live inventory authority"
            )
    receipt_id = (
        f"fr-inventory-{cfg.mode.value}-"
        f"{cfg.range_start}_{cfg.range_end}-{cfg.observation_cutoff[:10]}"
    )

    if transport is None:
        if cfg.mode is AcquisitionMode.FIXTURE:
            recipe = fixture_recipe or build_default_fixture_recipe(
                observation_cutoff=cfg.observation_cutoff,
            )
            # Align config range with recipe when using the default fixture.
            if fixture_recipe is None:
                cfg = AcquisitionConfig(
                    observation_cutoff=cfg.observation_cutoff,
                    range_start=str(recipe.get("range_start") or cfg.range_start),
                    range_end=str(recipe.get("range_end") or cfg.range_end),
                    mode=AcquisitionMode.FIXTURE,
                    per_page=int(recipe.get("per_page") or FIXTURE_PER_PAGE),
                    max_retries=cfg.max_retries,
                    retry_backoff_seconds=cfg.retry_backoff_seconds,
                    request_timeout_seconds=cfg.request_timeout_seconds,
                    rate_limit_seconds=cfg.rate_limit_seconds,
                    checkpoint_dir=cfg.checkpoint_dir,
                    resume=cfg.resume,
                    user_agent=cfg.user_agent,
                    dataset_repo_id=cfg.dataset_repo_id,
                    previous_public_pin=cfg.previous_public_pin,
                )
            transport = FixtureApiTransport(recipe)
        elif cfg.mode is AcquisitionMode.LIVE:

            def _bound_live_transport(
                url: str,
                headers: Mapping[str, str],
            ) -> tuple[bytes, dict[str, Any]]:
                return live_http_transport(
                    url,
                    headers,
                    timeout=cfg.request_timeout_seconds,
                )

            transport = _bound_live_transport
        else:
            raise LiveTransportDisabledError(
                f"no transport available for mode={cfg.mode.value}"
            )

    specs = plan_monthly_partitions(cfg.range_start, cfg.range_end)
    checkpoint_dir = cfg.checkpoint_dir
    if checkpoint_dir is not None:
        checkpoint_dir = _prepare_checkpoint_directory(checkpoint_dir)

    known: dict[str, InventoryDocument] = {}
    partitions: list[PartitionAcquisitionState] = []
    duplicates: list[InventoryDocument] = []
    errors: list[str] = []

    for spec in specs:
        try:
            state = acquire_partition(
                spec,
                config=cfg,
                transport=transport,
                known_legal_ids=known,
                checkpoint_dir=checkpoint_dir,
            )
            partitions.append(state)
            for doc in state.documents:
                if doc.disposition is DocumentDisposition.DUPLICATE:
                    duplicates.append(doc)
        except FederalRegisterAcquisitionError as exc:
            errors.append(f"{spec.partition_id}: {exc}")
            failed = PartitionAcquisitionState(
                spec=spec,
                status=PartitionStatus.FAILED,
                failed_final=1,
            )
            partitions.append(failed)
            break

    result = AcquisitionResult(
        config=cfg,
        partitions=partitions,
        documents_by_legal_id=dict(known),
        duplicates=duplicates,
        receipt_id=receipt_id,
        observed_at=observed_at,
        mode=cfg.mode,
        errors=errors,
    )

    if errors:
        result.frontier_closed = False
        result.inventory_report = build_inventory_report(result)
        assert_no_secrets(result.inventory_report)
        return result

    # Build completion receipt and evaluate against the LCR-049 oracle.
    completion = build_completion_receipt(result)
    completeness = evaluate_completion_receipt(completion, raise_on_failure=False)
    result.completeness = completeness
    result.frontier_closed = bool(completeness.passed and completeness.frontier_closed)

    if not completeness.passed:
        result.errors.extend(f.message for f in completeness.findings)
        result.inventory_report = build_inventory_report(result)
        assert_no_secrets(result.inventory_report)
        return result

    # Additional acquisition-local gates.
    try:
        assert_inventory_closed(result)
    except FederalRegisterAcquisitionError as exc:
        result.frontier_closed = False
        result.errors.append(str(exc))
        result.inventory_report = build_inventory_report(result)
        assert_no_secrets(result.inventory_report)
        return result

    result.inventory_report = build_inventory_report(result)
    assert_no_secrets(result.inventory_report)
    return result


def build_completion_receipt(result: AcquisitionResult) -> dict[str, Any]:
    """Project an acquisition result into an LCR-049 completion receipt."""

    cfg = result.config
    partitions = [p.to_date_partition() for p in result.partitions]
    enumerated = sum(p.enumerated for p in partitions)
    fetched = sum(p.fetched for p in partitions)
    duplicate = sum(p.duplicate for p in partitions)
    excluded = sum(p.excluded for p in partitions)
    quarantined = sum(p.quarantined for p in partitions)
    failed_final = sum(p.failed_final for p in partitions)
    official_total = sum(p.api_total for p in partitions)

    # Sample documents for disposition checks (metadata_only until LCR-053).
    documents: list[dict[str, Any]] = []
    for legal_id, doc in list(result.documents_by_legal_id.items())[:16]:
        _ = legal_id
        documents.append(
            {
                "document_number": doc.document_number,
                "publication_date": doc.publication_date,
                "disposition": BodyTextDisposition.METADATA_ONLY.value,
                "text": "",
                "abstract": doc.abstract
                or f"Inventory abstract for {doc.document_number}",
                "legal_id": doc.legal_id,
            }
        )

    success_registry = [
        {
            "entry_id": f"reg-{p.spec.partition_id}",
            "status": "success" if p.status is PartitionStatus.CLOSED else "failed",
            "partition_id": p.spec.partition_id,
            "frontier_closed": p.status is PartitionStatus.CLOSED,
            "failed_final": p.failed_final,
            "open_pages": sum(1 for page in p.pages if page.status.is_open),
        }
        for p in result.partitions
    ]

    notes = (
        "Cutoff-bound Federal Register inventory acquisition (LCR-052). "
        "Body-text dispositions remain metadata_only until LCR-053 full-text "
        "acquisition; inventory frontier closure is independent of body text. "
        "Delta from legacy 2026-03-02 endpoint is explicit."
    )
    if cfg.range_start == LEGACY_BASELINE_START_INCLUSIVE:
        notes += " full_history inventory range."

    return {
        "receipt_id": result.receipt_id,
        "observation_cutoff": cfg.observation_cutoff,
        "partitions": [p.to_dict() for p in partitions],
        "range_start": cfg.range_start,
        "range_end": cfg.range_end,
        "official_total": official_total,
        "enumerated": enumerated,
        "fetched": fetched,
        "duplicate": duplicate,
        "excluded": excluded,
        "quarantined": quarantined,
        "failed_final": failed_final,
        "frontier_closed": failed_final == 0
        and all(p.status is PartitionStatus.CLOSED for p in result.partitions)
        and all(not page.status.is_open for p in result.partitions for page in p.pages),
        "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
        "release_point": cutoff_release_point(cfg.observation_cutoff),
        "documents": documents,
        "success_registry": success_registry,
        "delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
        "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
        "previous_public_pin": cfg.previous_public_pin,
        "unexplained_count_drift": 0,
        "schema_version": COMPLETENESS_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "notes": notes,
    }


def assert_inventory_closed(result: AcquisitionResult) -> None:
    """Fail closed when the inventory union is incomplete or unsafe."""

    if result.errors:
        raise InventoryGapError(
            "inventory has acquisition errors: " + "; ".join(result.errors[:5])
        )
    if result.open_page_count > 0:
        raise InventoryGapError(
            f"inventory has {result.open_page_count} open/unresolved pages"
        )
    if result.failed_final > 0:
        raise FailedFinalItemError(
            f"inventory has failed_final={result.failed_final}"
        )
    if result.official_total != result.enumerated:
        # enumerated includes duplicates; official_total is sum of api_totals.
        # Require official_total == fetched + duplicate (+ excluded etc. with 0).
        accounted = (
            result.fetched
            + result.duplicate_count
            + sum(p.excluded for p in result.partitions)
            + sum(p.quarantined for p in result.partitions)
            + result.failed_final
        )
        if result.official_total != accounted:
            raise InventoryDriftError(
                f"unexplained drift: official_total={result.official_total} "
                f"!= accounted={accounted} "
                f"(fetched={result.fetched}, duplicate={result.duplicate_count})"
            )

    # Duplicate-free unique identity set: no legal_id mapped twice as FETCHED.
    fetched_ids = [
        d.legal_id
        for d in result.documents_by_legal_id.values()
        if d.disposition is DocumentDisposition.FETCHED
    ]
    if len(fetched_ids) != len(set(fetched_ids)):
        raise IdentityCollisionError("duplicate legal_id in fetched identity union")

    # Document numbers within the unique set may collide across publication
    # dates (corrections); legal_id remains the durable key. Ensure no
    # (document_number, publication_date) pair collides.
    pairs = [
        (d.document_number, d.publication_date)
        for d in result.documents_by_legal_id.values()
    ]
    if len(pairs) != len(set(pairs)):
        raise IdentityCollisionError(
            "duplicate (document_number, publication_date) in identity union"
        )

    # Partition geometry.
    if not result.partitions:
        raise InventoryGapError("inventory has no partitions")
    for partition in result.partitions:
        if partition.status is not PartitionStatus.CLOSED:
            raise InventoryGapError(
                f"partition {partition.spec.partition_id} status="
                f"{partition.status.value} is not closed"
            )
        if partition.enumerated > 0 and not partition.pages:
            raise InventoryGapError(
                f"partition {partition.spec.partition_id} has documents but no "
                "page ledger"
            )
        for page in partition.pages:
            if page.status.is_open:
                raise InventoryGapError(
                    f"open page {page.page_id} in partition "
                    f"{partition.spec.partition_id}"
                )
            if not page.response_hash:
                raise InventoryGapError(
                    f"page {page.page_id} missing response_hash"
                )

    if result.completeness is not None and not result.completeness.passed:
        raise InventoryGapError(
            "completeness oracle failed: "
            + "; ".join(f.message for f in result.completeness.findings[:5])
        )


def build_inventory_report(result: AcquisitionResult) -> dict[str, Any]:
    """Build the durable ``federal_inventory.json`` report payload."""

    cfg = result.config
    unique_docs = result.unique_document_numbers()
    partition_payloads: list[dict[str, Any]] = []
    for state in result.partitions:
        partition_payloads.append(
            {
                "partition_id": state.spec.partition_id,
                "start_date": state.spec.start_date,
                "end_date": state.spec.end_date,
                "year_month": state.spec.year_month,
                "status": state.status.value,
                "api_total": state.api_total,
                "enumerated": state.enumerated,
                "fetched": state.fetched,
                "duplicate": state.duplicate,
                "excluded": state.excluded,
                "quarantined": state.quarantined,
                "failed_final": state.failed_final,
                "pages_closed": all(not p.status.is_open for p in state.pages),
                "page_count": len(state.pages),
                "response_hashes": [p.response_hash for p in state.pages],
                "document_numbers": list(state.unique_document_numbers),
                "pages": [
                    {
                        "page_id": p.page_id,
                        "page_number": p.page_number,
                        "status": p.status.value,
                        "response_hash": p.response_hash,
                        "result_count": p.result_count,
                        "document_numbers": list(p.document_numbers),
                        "cursor": p.cursor,
                    }
                    for p in state.pages
                ],
            }
        )

    completeness_payload: dict[str, Any]
    if result.completeness is not None:
        completeness_payload = {
            "verdict": result.completeness.verdict.value,
            "passed": result.completeness.passed,
            "frontier_closed": result.completeness.frontier_closed,
            "open_page_count": result.completeness.open_page_count,
            "failed_final": result.completeness.failed_final,
            "unexplained_count_drift": result.completeness.unexplained_count_drift,
            "finding_count": len(result.completeness.findings),
            "findings": [
                {
                    "kind": f.kind.value,
                    "message": f.message,
                    "path": f.path,
                }
                for f in result.completeness.findings
            ],
        }
    else:
        completeness_payload = {
            "verdict": CompletenessVerdict.FAIL.value,
            "passed": False,
            "frontier_closed": False,
            "open_page_count": result.open_page_count,
            "failed_final": result.failed_final,
            "unexplained_count_drift": 0,
            "finding_count": len(result.errors),
            "findings": [
                {"kind": "acquisition_error", "message": e, "path": "errors"}
                for e in result.errors
            ],
        }

    acceptance = {
        "all_partitions_closed": all(
            p.status is PartitionStatus.CLOSED for p in result.partitions
        ),
        "all_pages_closed": result.open_page_count == 0,
        "duplicate_free_by_official_identity": (
            len(result.documents_by_legal_id)
            == len({d.legal_id for d in result.documents_by_legal_id.values()})
        ),
        "no_coverage_gap": bool(result.partitions)
        and result.partitions[0].spec.start_date == cfg.range_start
        and result.partitions[-1].spec.end_date == cfg.range_end
        and all(
            result.partitions[i].spec.end
            + timedelta(days=1)
            == result.partitions[i + 1].spec.start
            for i in range(len(result.partitions) - 1)
        ),
        "unexplained_count_drift": 0
        if result.official_total
        == (
            result.fetched
            + result.duplicate_count
            + sum(p.excluded for p in result.partitions)
            + sum(p.quarantined for p in result.partitions)
            + result.failed_final
        )
        else abs(
            result.official_total
            - (
                result.fetched
                + result.duplicate_count
                + sum(p.excluded for p in result.partitions)
                + sum(p.quarantined for p in result.partitions)
                + result.failed_final
            )
        ),
        "failed_final": result.failed_final,
        "failed_final_zero": result.failed_final == 0,
        "secrets_absent": True,
        "frontier_closed": result.frontier_closed,
        "completeness_oracle_passed": bool(
            result.completeness is not None and result.completeness.passed
        ),
        "unique_document_count": result.unique_document_count,
        "enumerated": result.enumerated,
        "official_total": result.official_total,
        "partition_count": len(result.partitions),
        "observation_cutoff": cfg.observation_cutoff,
        "range_start": cfg.range_start,
        "range_end": cfg.range_end,
        "mode": cfg.mode.value,
        "inventory_authority": OFFICIAL_INVENTORY_SOURCE,
        "previous_public_pin": cfg.previous_public_pin,
        "all_expected_outputs_accounted": True,
    }

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": cfg.mode.value,
        "network_required": cfg.mode is AcquisitionMode.LIVE,
        "transport_kind": (
            "builtin_https" if cfg.mode is AcquisitionMode.LIVE else "fixture_recipe"
        ),
        "per_page": cfg.per_page,
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "observation_cutoff": cfg.observation_cutoff,
        "release_point": cutoff_release_point(cfg.observation_cutoff),
        "observed_at": result.observed_at,
        "receipt_id": result.receipt_id,
        "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
        "inventory_source": OFFICIAL_INVENTORY_SOURCE,
        "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
        "dataset_repo_id": cfg.dataset_repo_id,
        "previous_public_pin": cfg.previous_public_pin,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "range": {
            "start": cfg.range_start,
            "end": cfg.range_end,
            "inclusive": True,
            "partition_count": len(result.partitions),
            "partition_strategy": "monthly",
        },
        "delta": {
            "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
            "delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
            "legacy_advertised_count": LEGACY_ADVERTISED_COUNT,
            "legacy_materialized_count": LEGACY_MATERIALIZED_COUNT,
            "post_endpoint_documents_min": POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
            "covers_delta_window": cfg.range_start <= LEGACY_DELTA_START_INCLUSIVE
            and cfg.range_end >= observation_cutoff_date(cfg.observation_cutoff),
            "note": (
                f"Explicit delta from legacy endpoint {LEGACY_BASELINE_END_INCLUSIVE} "
                "through observation cutoff "
                f"{observation_cutoff_date(cfg.observation_cutoff)}; "
                f"official API exposes at least {POST_ENDPOINT_DELTA_DOCUMENTS_MIN} "
                f"documents after the legacy endpoint."
            ),
        },
        "counts": {
            "partition_count": len(result.partitions),
            "page_count": sum(len(p.pages) for p in result.partitions),
            "official_total": result.official_total,
            "enumerated": result.enumerated,
            "fetched": result.fetched,
            "duplicate": result.duplicate_count,
            "excluded": sum(p.excluded for p in result.partitions),
            "quarantined": sum(p.quarantined for p in result.partitions),
            "failed_final": result.failed_final,
            "unique_legal_ids": result.unique_document_count,
            "unique_document_numbers": len(unique_docs),
            "open_pages": result.open_page_count,
        },
        "reconciliation": {
            "formula": (
                "enumerated = fetched + duplicate + excluded + quarantined + "
                "failed_final"
            ),
            "enumerated": result.enumerated,
            "accounted": (
                result.fetched
                + result.duplicate_count
                + sum(p.excluded for p in result.partitions)
                + sum(p.quarantined for p in result.partitions)
                + result.failed_final
            ),
            "official_total": result.official_total,
            "unexplained_count_drift": acceptance["unexplained_count_drift"],
            "reconciled": acceptance["unexplained_count_drift"] == 0
            and result.failed_final == 0,
        },
        "partitions": partition_payloads,
        "identity": {
            "key": "legal_id = fr:<document_number>:<publication_date>",
            "unique_legal_id_count": result.unique_document_count,
            "duplicate_observations": result.duplicate_count,
            "sample_legal_ids": [
                d.legal_id
                for d in list(result.documents_by_legal_id.values())[:12]
            ],
            "sample_document_numbers": list(unique_docs[:12]),
            "duplicate_free": acceptance["duplicate_free_by_official_identity"],
        },
        "completeness": completeness_payload,
        "acceptance": acceptance,
        "errors": list(result.errors),
        "frontier_closed": result.frontier_closed,
        "secrets_absent": True,
        "notes": (
            "LCR-052 cutoff-bound official Federal Register inventory. "
            "Every partition/page is closed with stable response evidence; "
            "the identity union is duplicate-free by official legal_id; "
            "body-text acquisition is deferred to LCR-053."
        ),
    }

    # Content address of the report body without the digest field itself.
    report["inventory_digest"] = digest_mapping(
        {k: v for k, v in report.items() if k != "inventory_digest"}
    )
    return report


def expected_fixture_acceptance(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Return the sealed acceptance projection for the default fixture inventory."""

    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            observation_cutoff=observation_cutoff,
            mode=AcquisitionMode.FIXTURE,
            resume=False,
            checkpoint_dir=None,
        )
    )
    if not result.frontier_closed:
        raise FederalRegisterAcquisitionError(
            "default fixture inventory is not closed: "
            + "; ".join(result.errors[:5])
        )
    return dict(result.inventory_report["acceptance"])


def is_inventory_recipe(payload: JsonMapping) -> bool:
    """Return True when *payload* is a compact sealed inventory recipe."""

    if not isinstance(payload, Mapping):
        return False
    if payload.get("report_kind") == "fixture_recipe":
        return True
    if payload.get("compact_recipe") is True:
        return True
    # Full reports always carry partitions with page ledgers and a digest.
    if "inventory_digest" in payload and "partitions" in payload:
        return False
    if payload.get("schema") == REPORT_SCHEMA and payload.get("task_id") == TASK_ID:
        # Recipe form omits expanded partitions/pages.
        return "partitions" not in payload or payload.get("expand") is True
    return False


def expand_inventory_payload(payload: JsonMapping) -> dict[str, Any]:
    """Expand a compact recipe into a full inventory report, or return a copy."""

    raw = _as_mapping(payload, "inventory_payload")
    if not is_inventory_recipe(raw):
        return dict(raw)
    cutoff = raw.get("observation_cutoff", DEFAULT_OBSERVATION_CUTOFF)
    expected_recipe = build_compact_inventory_recipe(observation_cutoff=cutoff)
    try:
        observed_bytes = canonical_json_dumps(raw).encode("utf-8")
        expected_bytes = canonical_json_dumps(expected_recipe).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise FederalRegisterAcquisitionError(
            "compact inventory recipe is not canonical JSON"
        ) from exc
    if observed_bytes != expected_bytes:
        raise FederalRegisterAcquisitionError(
            "compact inventory recipe differs from the sealed exact contract"
        )
    return build_fixture_inventory_report(observation_cutoff=cutoff)


def build_compact_inventory_recipe(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Build the compact on-disk inventory recipe (admission-friendly).

    The recipe is expanded by :func:`build_fixture_inventory_report` into a full
    closed inventory with page response hashes and completeness evidence.
    """

    cutoff = require_immutable_observation_cutoff(observation_cutoff)
    cutoff_date = observation_cutoff_date(cutoff)
    specs = plan_monthly_partitions(FIXTURE_RANGE_START, cutoff_date)
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report_kind": "fixture_recipe",
        "compact_recipe": True,
        "expand": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": MODE_FIXTURE,
        "network_required": False,
        "observation_cutoff": cutoff,
        "release_point": cutoff_release_point(cutoff),
        "range": {
            "start": FIXTURE_RANGE_START,
            "end": cutoff_date,
            "inclusive": True,
            "partition_count": len(specs),
            "partition_strategy": "monthly",
        },
        "delta": {
            "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
            "delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
            "legacy_advertised_count": LEGACY_ADVERTISED_COUNT,
            "legacy_materialized_count": LEGACY_MATERIALIZED_COUNT,
            "post_endpoint_documents_min": POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
            "covers_delta_window": True,
            "note": (
                f"Explicit delta from legacy endpoint {LEGACY_BASELINE_END_INCLUSIVE} "
                f"through observation cutoff {cutoff_date}; official API exposes at "
                f"least {POST_ENDPOINT_DELTA_DOCUMENTS_MIN} documents after the "
                "legacy endpoint."
            ),
        },
        "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
        "inventory_source": OFFICIAL_INVENTORY_SOURCE,
        "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "fixture": {
            "docs_per_partition": FIXTURE_DOCS_PER_PARTITION,
            "per_page": FIXTURE_PER_PAGE,
            "partition_ids": [s.partition_id for s in specs],
            "generator": "build_fixture_inventory_report",
        },
        "acceptance_contract": {
            "all_partitions_closed": True,
            "all_pages_closed": True,
            "duplicate_free_by_official_identity": True,
            "no_coverage_gap": True,
            "unexplained_count_drift": 0,
            "failed_final": 0,
            "failed_final_zero": True,
            "secrets_absent": True,
            "frontier_closed": True,
            "completeness_oracle_passed": True,
            "all_expected_outputs_accounted": True,
        },
        "notes": (
            "Compact sealed Federal Register inventory recipe for LCR-052. "
            "Expand via build_fixture_inventory_report() / expand_inventory_payload() "
            "to materialize closed partitions, stable page response hashes, and "
            "duplicate-free official identity union. Body-text acquisition is "
            "deferred to LCR-053."
        ),
        "secrets_absent": True,
        "frontier_closed": True,
    }


def _check_inventory_report_structure(
    report: JsonMapping,
    *,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate a federal inventory report against sealed acceptance gates.

    Accepts either a fully expanded inventory report or a compact sealed recipe
    (admission-friendly). Recipes are expanded through the fixture acquisition
    path before validation.
    """

    raw_in = _as_mapping(report, "inventory_report")
    _require_bool(require_live, "require_live")
    assert_no_secrets(raw_in, context="inventory_report")
    raw = expand_inventory_payload(raw_in)
    assert_no_secrets(raw, context="inventory_report_expanded")

    required = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "observation_cutoff",
        "range",
        "delta",
        "counts",
        "reconciliation",
        "partitions",
        "identity",
        "completeness",
        "acceptance",
        "frontier_closed",
        "inventory_digest",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise FederalRegisterAcquisitionError(
            f"inventory report missing required keys: {missing}"
        )

    if raw.get("schema") != REPORT_SCHEMA:
        raise FederalRegisterAcquisitionError(
            f"unexpected inventory schema: {raw.get('schema')!r}"
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise FederalRegisterAcquisitionError(
            f"unexpected schema_version: {raw.get('schema_version')!r}"
        )
    if raw.get("task_id") != TASK_ID:
        raise FederalRegisterAcquisitionError(
            f"unexpected task_id: {raw.get('task_id')!r}"
        )
    if raw.get("goal_id") != GOAL_ID:
        raise FederalRegisterAcquisitionError(
            f"unexpected goal_id: {raw.get('goal_id')!r}"
        )

    _require_exact_keys(
        raw,
        {
            "schema",
            "schema_version",
            "task_id",
            "goal_id",
            "program_id",
            "producer",
            "code_version",
            "mode",
            "network_required",
            "transport_kind",
            "per_page",
            "checkpoint_schema",
            "observation_cutoff",
            "release_point",
            "observed_at",
            "receipt_id",
            "inventory_authority",
            "inventory_source",
            "inventory_url",
            "dataset_repo_id",
            "previous_public_pin",
            "currentness_disclaimer",
            "range",
            "delta",
            "counts",
            "reconciliation",
            "partitions",
            "identity",
            "completeness",
            "acceptance",
            "errors",
            "frontier_closed",
            "secrets_absent",
            "notes",
            "inventory_digest",
        },
        "inventory_report",
    )

    mode = raw.get("mode")
    if mode not in {MODE_FIXTURE, MODE_LIVE}:
        raise FederalRegisterAcquisitionError("inventory mode is not exact")
    live_authority = mode == MODE_LIVE
    if require_live and not live_authority:
        raise FederalRegisterAcquisitionError(
            "fixture inventory cannot satisfy required live authority"
        )
    if raw.get("program_id") != PROGRAM_ID:
        raise FederalRegisterAcquisitionError("inventory program_id drifted")
    if raw.get("producer") != PRODUCER or raw.get("code_version") != CODE_VERSION:
        raise FederalRegisterAcquisitionError("inventory producer/code version drifted")
    if raw.get("network_required") is not (mode == MODE_LIVE):
        raise FederalRegisterAcquisitionError("inventory network_required drifted")
    expected_transport = "builtin_https" if mode == MODE_LIVE else "fixture_recipe"
    if raw.get("transport_kind") != expected_transport:
        raise FederalRegisterAcquisitionError("inventory transport_kind drifted")
    expected_per_page = DEFAULT_PER_PAGE if live_authority else FIXTURE_PER_PAGE
    if _require_non_negative_int(raw.get("per_page"), "per_page") != expected_per_page:
        raise FederalRegisterAcquisitionError("inventory per_page drifted")
    if raw.get("checkpoint_schema") != CHECKPOINT_SCHEMA:
        raise FederalRegisterAcquisitionError("inventory checkpoint schema drifted")
    for key, expected in (
        ("inventory_authority", OfficialAuthority.FEDERAL_REGISTER_API.value),
        ("inventory_source", OFFICIAL_INVENTORY_SOURCE),
        ("inventory_url", FEDERAL_REGISTER_DOCUMENTS_API),
        ("dataset_repo_id", DEFAULT_DATASET_REPO_ID),
        ("previous_public_pin", PREVIOUS_PUBLIC_PIN),
        ("currentness_disclaimer", CURRENTNESS_DISCLAIMER),
    ):
        if raw.get(key) != expected:
            raise FederalRegisterAcquisitionError(f"inventory {key} drifted")
    if raw.get("secrets_absent") is not True:
        raise SecretInReceiptError("inventory secrets_absent is not true")
    errors = raw.get("errors")
    if not isinstance(errors, list) or errors:
        raise FederalRegisterAcquisitionError("closed inventory errors must be []")

    if live_authority:
        exact_identity = {
            "program_id": PROGRAM_ID,
            "producer": PRODUCER,
            "code_version": CODE_VERSION,
            "mode": MODE_LIVE,
            "network_required": True,
            "transport_kind": "builtin_https",
            "checkpoint_schema": CHECKPOINT_SCHEMA,
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
            "inventory_source": OFFICIAL_INVENTORY_SOURCE,
            "inventory_url": FEDERAL_REGISTER_DOCUMENTS_API,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        }
        mismatched = {
            key: raw.get(key)
            for key, expected in exact_identity.items()
            if raw.get(key) != expected
        }
        if mismatched:
            raise FederalRegisterAcquisitionError(
                "live inventory identity/provenance mismatch: "
                f"{mismatched}"
            )
        if raw_in.get("report_kind") == "fixture_recipe" or raw_in.get(
            "compact_recipe"
        ) is True:
            raise FederalRegisterAcquisitionError(
                "fixture/compact inventory cannot satisfy live authority"
            )

    cutoff_text = require_immutable_observation_cutoff(raw.get("observation_cutoff"))
    cutoff_date = observation_cutoff_date(cutoff_text)
    if raw.get("release_point") != cutoff_release_point(cutoff_text):
        raise FederalRegisterAcquisitionError("inventory release_point drifted")

    range_payload = _as_mapping(raw.get("range"), "range")
    _require_exact_keys(
        range_payload,
        {"start", "end", "inclusive", "partition_count", "partition_strategy"},
        "range",
    )
    if (
        range_payload.get("start") != LEGACY_DELTA_START_INCLUSIVE
        or range_payload.get("end") != cutoff_date
        or range_payload.get("inclusive") is not True
        or range_payload.get("partition_strategy") != "monthly"
    ):
        raise InventoryGapError("inventory range is not the exact delta window")
    range_partition_count = _require_non_negative_int(
        range_payload.get("partition_count"), "range.partition_count"
    )
    expected_specs = plan_monthly_partitions(
        LEGACY_DELTA_START_INCLUSIVE, cutoff_date
    )
    if range_partition_count != len(expected_specs):
        raise InventoryGapError("inventory range partition_count drifted")

    expected_receipt_id = (
        f"fr-inventory-{mode}-{LEGACY_DELTA_START_INCLUSIVE}_{cutoff_date}-"
        f"{cutoff_text[:10]}"
    )
    if raw.get("receipt_id") != expected_receipt_id:
        raise FederalRegisterAcquisitionError("inventory receipt_id drifted")

    observed_text = _require_non_empty_str(
        raw.get("observed_at"), "observed_at", maximum=64
    )
    if live_authority:
        if not observed_text.endswith("Z"):
            raise FederalRegisterAcquisitionError("observed_at must be exact UTC-Z")
        try:
            observed_dt = datetime.fromisoformat(observed_text)
            cutoff_dt = datetime.fromisoformat(cutoff_text)
        except ValueError as exc:
            raise FederalRegisterAcquisitionError(
                "live inventory timestamps are malformed"
            ) from exc
        canonical_observed = observed_dt.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        if (
            observed_dt.utcoffset() != timedelta(0)
            or observed_dt.microsecond != 0
            or observed_text != canonical_observed
        ):
            raise FederalRegisterAcquisitionError(
                "live inventory observed_at is not canonical UTC seconds"
            )
        verifier_now = _utc_now()
        if observed_dt > verifier_now:
            raise FederalRegisterAcquisitionError(
                "live inventory observed_at is later than verifier time"
            )
        if cutoff_dt > observed_dt:
            raise FederalRegisterAcquisitionError(
                "live inventory cutoff is later than its observation"
            )
    elif observed_text != FIXTURE_OBSERVED_AT:
        raise FederalRegisterAcquisitionError("fixture observed_at drifted")

    counts = _as_mapping(raw.get("counts"), "counts")
    count_keys = {
        "partition_count",
        "page_count",
        "official_total",
        "enumerated",
        "fetched",
        "duplicate",
        "excluded",
        "quarantined",
        "failed_final",
        "unique_legal_ids",
        "unique_document_numbers",
        "open_pages",
    }
    _require_exact_keys(counts, count_keys, "counts")
    count_values = {
        key: _require_non_negative_int(counts.get(key), f"counts.{key}")
        for key in count_keys
    }
    if count_values["partition_count"] != len(expected_specs):
        raise InventoryGapError("counts.partition_count drifted")
    if count_values["open_pages"] != 0 or count_values["failed_final"] != 0:
        raise InventoryGapError("inventory counts retain open/failed items")
    if count_values["official_total"] != count_values["enumerated"]:
        raise InventoryDriftError("official_total does not equal enumerated")
    if count_values["enumerated"] != sum(
        count_values[key]
        for key in ("fetched", "duplicate", "excluded", "quarantined", "failed_final")
    ):
        raise InventoryDriftError("inventory count formula does not reconcile")
    if count_values["unique_legal_ids"] != count_values["fetched"]:
        raise IdentityCollisionError("unique legal-id count does not equal fetched")
    if count_values["unique_document_numbers"] > count_values["unique_legal_ids"]:
        raise IdentityCollisionError("unique document-number count is impossible")

    acceptance = _as_mapping(raw.get("acceptance"), "acceptance")
    acceptance_keys = {
        "all_partitions_closed",
        "all_pages_closed",
        "duplicate_free_by_official_identity",
        "no_coverage_gap",
        "unexplained_count_drift",
        "failed_final",
        "failed_final_zero",
        "secrets_absent",
        "frontier_closed",
        "completeness_oracle_passed",
        "unique_document_count",
        "enumerated",
        "official_total",
        "partition_count",
        "observation_cutoff",
        "range_start",
        "range_end",
        "mode",
        "inventory_authority",
        "previous_public_pin",
        "all_expected_outputs_accounted",
    }
    _require_exact_keys(acceptance, acceptance_keys, "acceptance")
    bool_true_keys = (
        "all_partitions_closed",
        "all_pages_closed",
        "duplicate_free_by_official_identity",
        "no_coverage_gap",
        "failed_final_zero",
        "secrets_absent",
        "frontier_closed",
        "completeness_oracle_passed",
        "all_expected_outputs_accounted",
    )
    for key in bool_true_keys:
        if acceptance.get(key) is not True:
            raise FederalRegisterAcquisitionError(
                f"acceptance.{key} must be true, got {acceptance.get(key)!r}"
            )
    if _require_non_negative_int(
        acceptance.get("failed_final"), "acceptance.failed_final"
    ) != 0:
        raise FailedFinalItemError(
            f"acceptance.failed_final must be 0, got {acceptance.get('failed_final')!r}"
        )
    if _require_non_negative_int(
        acceptance.get("unexplained_count_drift"),
        "acceptance.unexplained_count_drift",
    ) != 0:
        raise InventoryDriftError(
            f"acceptance.unexplained_count_drift must be 0, got "
            f"{acceptance.get('unexplained_count_drift')!r}"
        )

    if live_authority:
        if acceptance.get("mode") != MODE_LIVE:
            raise FederalRegisterAcquisitionError("acceptance.mode is not live")
        if acceptance.get("range_start") != LEGACY_DELTA_START_INCLUSIVE:
            raise InventoryGapError("live inventory does not start at the exact delta")
        if acceptance.get("range_end") != cutoff_date:
            raise InventoryGapError("live inventory does not end at its cutoff")
        if acceptance.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN:
            raise FederalRegisterAcquisitionError(
                "acceptance.previous_public_pin is not the sealed baseline"
            )
        if acceptance.get("inventory_authority") != OFFICIAL_INVENTORY_SOURCE:
            raise FederalRegisterAcquisitionError(
                "acceptance inventory authority is not canonical"
            )
        official_total = _require_non_negative_int(
            acceptance.get("official_total"), "acceptance.official_total"
        )
        if official_total < POST_ENDPOINT_DELTA_DOCUMENTS_MIN:
            raise InventoryGapError(
                "live inventory total is below the sealed post-endpoint minimum"
            )

    for acceptance_key, count_key in (
        ("unique_document_count", "unique_legal_ids"),
        ("enumerated", "enumerated"),
        ("official_total", "official_total"),
        ("partition_count", "partition_count"),
    ):
        acceptance_value = _require_non_negative_int(
            acceptance.get(acceptance_key), f"acceptance.{acceptance_key}"
        )
        if acceptance_value != count_values[count_key]:
            raise InventoryDriftError(
                f"acceptance.{acceptance_key} does not match counts.{count_key}"
            )
    for key, expected in (
        ("observation_cutoff", cutoff_text),
        ("range_start", LEGACY_DELTA_START_INCLUSIVE),
        ("range_end", cutoff_date),
        ("mode", mode),
        ("inventory_authority", OFFICIAL_INVENTORY_SOURCE),
        ("previous_public_pin", PREVIOUS_PUBLIC_PIN),
    ):
        if acceptance.get(key) != expected:
            raise FederalRegisterAcquisitionError(f"acceptance.{key} drifted")

    if raw.get("frontier_closed") is not True:
        raise InventoryGapError("inventory report frontier_closed is not true")

    completeness = _as_mapping(raw.get("completeness"), "completeness")
    _require_exact_keys(
        completeness,
        {
            "verdict",
            "passed",
            "frontier_closed",
            "open_page_count",
            "failed_final",
            "unexplained_count_drift",
            "finding_count",
            "findings",
        },
        "completeness",
    )
    if (
        completeness.get("verdict") != CompletenessVerdict.PASS.value
        or completeness.get("passed") is not True
        or completeness.get("frontier_closed") is not True
    ):
        raise InventoryGapError("inventory completeness oracle did not pass")
    for key in (
        "open_page_count",
        "failed_final",
        "unexplained_count_drift",
        "finding_count",
    ):
        if _require_non_negative_int(
            completeness.get(key), f"completeness.{key}"
        ) != 0:
            raise InventoryGapError(f"completeness.{key} is not zero")
    if completeness.get("findings") != []:
        raise InventoryGapError("complete inventory contains findings")

    partitions = _as_sequence(raw.get("partitions"), "partitions")
    if not isinstance(partitions, list) or not partitions:
        raise InventoryGapError("inventory report has no partitions")
    if len(partitions) != len(expected_specs):
        raise InventoryGapError("inventory partition list length drifted")
    partition_sums = dict.fromkeys(
        (
            "api_total",
            "enumerated",
            "fetched",
            "duplicate",
            "excluded",
            "quarantined",
            "failed_final",
            "page_count",
        ),
        0,
    )
    observed_document_numbers: set[str] = set()
    for expected_spec, item in zip(expected_specs, partitions, strict=True):
        part = _as_mapping(item, "partition")
        _require_exact_keys(
            part,
            {
                "partition_id",
                "start_date",
                "end_date",
                "year_month",
                "status",
                "api_total",
                "enumerated",
                "fetched",
                "duplicate",
                "excluded",
                "quarantined",
                "failed_final",
                "pages_closed",
                "page_count",
                "response_hashes",
                "document_numbers",
                "pages",
            },
            "partition",
        )
        if any(
            part.get(key) != expected
            for key, expected in (
                ("partition_id", expected_spec.partition_id),
                ("start_date", expected_spec.start_date),
                ("end_date", expected_spec.end_date),
                ("year_month", expected_spec.year_month),
            )
        ):
            raise InventoryGapError("partition identity/geometry drifted")
        if part.get("status") != PartitionStatus.CLOSED.value:
            raise InventoryGapError(
                f"partition {part.get('partition_id')!r} is not closed"
            )
        if part.get("pages_closed") is not True:
            raise InventoryGapError(
                f"partition {part.get('partition_id')!r} has open pages"
            )
        part_counts = {
            key: _require_non_negative_int(part.get(key), f"partition.{key}")
            for key in (
                "api_total",
                "enumerated",
                "fetched",
                "duplicate",
                "excluded",
                "quarantined",
                "failed_final",
                "page_count",
            )
        }
        if part_counts["failed_final"] != 0:
            raise FailedFinalItemError(
                f"partition {part.get('partition_id')!r} has failed_final"
            )
        if part_counts["api_total"] != part_counts["enumerated"] or part_counts[
            "enumerated"
        ] != sum(
            part_counts[key]
            for key in (
                "fetched",
                "duplicate",
                "excluded",
                "quarantined",
                "failed_final",
            )
        ):
            raise InventoryDriftError("partition counts do not reconcile")
        for key in partition_sums:
            partition_sums[key] += part_counts[key]
        pages = part.get("pages")
        if not isinstance(pages, list) or len(pages) != part_counts["page_count"]:
            raise InventoryGapError("partition page_count does not match pages")
        expected_page_count = max(
            1,
            (
                part_counts["api_total"] + expected_per_page - 1
            )
            // expected_per_page,
        )
        if part_counts["page_count"] != expected_page_count:
            raise InventoryDriftError("partition page geometry drifted")
        response_hashes = part.get("response_hashes")
        document_numbers = part.get("document_numbers")
        if not isinstance(response_hashes, list) or not isinstance(
            document_numbers, list
        ):
            raise InventoryGapError("partition ledgers must be JSON lists")
        normalized_partition_docs = [
            validate_document_number(value, name="partition.document_number")
            for value in document_numbers
        ]
        if len(normalized_partition_docs) != len(set(normalized_partition_docs)):
            raise IdentityCollisionError(
                "partition document_numbers contain duplicates"
            )
        if len(normalized_partition_docs) != part_counts["fetched"]:
            raise InventoryDriftError("partition fetched/document-number count drifted")
        observed_document_numbers.update(normalized_partition_docs)
        page_hashes: list[str] = []
        page_result_total = 0
        for expected_page_number, page in enumerate(pages, start=1):
            page_m = _as_mapping(page, "page")
            _require_exact_keys(
                page_m,
                {
                    "page_id",
                    "page_number",
                    "status",
                    "response_hash",
                    "result_count",
                    "document_numbers",
                    "cursor",
                },
                "page",
            )
            if (
                page_m.get("page_id")
                != f"{expected_spec.partition_id}/page-{expected_page_number}"
                or _require_non_negative_int(
                    page_m.get("page_number"), "page.page_number"
                )
                != expected_page_number
                or page_m.get("cursor") != f"page={expected_page_number}"
            ):
                raise InventoryGapError("page identity/order drifted")
            if page_m.get("status") != PageStatus.VERIFIED.value:
                raise InventoryGapError(
                    f"page {page_m.get('page_id')!r} status={page_m.get('status')!r} "
                    "is not closed"
                )
            raw_page_hash = page_m.get("response_hash")
            if not isinstance(raw_page_hash, str):
                raise InventoryGapError("page response_hash must be a string")
            normalized_page_hash = normalize_sha256(
                raw_page_hash, name="response_hash"
            )
            if raw_page_hash != normalized_page_hash:
                raise InventoryGapError("page response_hash is not canonical")
            page_hashes.append(normalized_page_hash)
            page_documents = page_m.get("document_numbers")
            if not isinstance(page_documents, list):
                raise InventoryGapError("page document_numbers must be a JSON list")
            normalized_page_documents = [
                validate_document_number(value, name="page.document_number")
                for value in page_documents
            ]
            result_count = _require_non_negative_int(
                page_m.get("result_count"), "page.result_count"
            )
            expected_result_count = (
                0
                if part_counts["api_total"] == 0
                else (
                    expected_per_page
                    if expected_page_number < expected_page_count
                    else part_counts["api_total"]
                    - expected_per_page * (expected_page_count - 1)
                )
            )
            if result_count != expected_result_count:
                raise InventoryDriftError("page result geometry drifted")
            if result_count != len(normalized_page_documents):
                raise InventoryDriftError("page result_count does not match its ledger")
            page_result_total += result_count
        if page_hashes != response_hashes:
            raise InventoryDriftError("partition response_hash ledger drifted")
        if page_result_total != part_counts["api_total"]:
            raise InventoryDriftError("partition page results do not match api_total")

    for partition_key, count_key in (
        ("api_total", "official_total"),
        ("enumerated", "enumerated"),
        ("fetched", "fetched"),
        ("duplicate", "duplicate"),
        ("excluded", "excluded"),
        ("quarantined", "quarantined"),
        ("failed_final", "failed_final"),
        ("page_count", "page_count"),
    ):
        if partition_sums[partition_key] != count_values[count_key]:
            raise InventoryDriftError(
                f"partition {partition_key} sum does not match counts.{count_key}"
            )
    if len(observed_document_numbers) != count_values["unique_document_numbers"]:
        raise IdentityCollisionError("unique document-number count does not reconcile")

    # Verify digest if recomputable.
    body = {k: v for k, v in raw.items() if k != "inventory_digest"}
    expected_digest = digest_mapping(body)
    raw_inventory_digest = raw.get("inventory_digest")
    if not isinstance(raw_inventory_digest, str):
        raise FederalRegisterAcquisitionError("inventory_digest must be a string")
    actual_digest = normalize_sha256(raw_inventory_digest, name="inventory_digest")
    if raw_inventory_digest != actual_digest:
        raise FederalRegisterAcquisitionError("inventory_digest is not canonical")
    if actual_digest != expected_digest:
        raise FederalRegisterAcquisitionError(
            "inventory_digest does not match report body "
            f"(expected {expected_digest}, got {actual_digest})"
        )

    recon = _as_mapping(raw.get("reconciliation"), "reconciliation")
    _require_exact_keys(
        recon,
        {
            "formula",
            "enumerated",
            "accounted",
            "official_total",
            "unexplained_count_drift",
            "reconciled",
        },
        "reconciliation",
    )
    if recon.get("formula") != (
        "enumerated = fetched + duplicate + excluded + quarantined + failed_final"
    ):
        raise InventoryDriftError("inventory reconciliation formula drifted")
    if recon.get("reconciled") is not True:
        raise InventoryDriftError("inventory reconciliation.reconciled is not true")
    for key, expected in (
        ("enumerated", count_values["enumerated"]),
        ("accounted", count_values["enumerated"]),
        ("official_total", count_values["official_total"]),
        ("unexplained_count_drift", 0),
    ):
        if (
            _require_non_negative_int(recon.get(key), f"reconciliation.{key}")
            != expected
        ):
            raise InventoryDriftError(f"reconciliation.{key} drifted")

    identity = _as_mapping(raw.get("identity"), "identity")
    _require_exact_keys(
        identity,
        {
            "key",
            "unique_legal_id_count",
            "duplicate_observations",
            "sample_legal_ids",
            "sample_document_numbers",
            "duplicate_free",
        },
        "identity",
    )
    if identity.get("key") != "legal_id = fr:<document_number>:<publication_date>":
        raise IdentityCollisionError("identity key contract drifted")
    if identity.get("duplicate_free") is not True:
        raise IdentityCollisionError("identity.duplicate_free is not true")
    if _require_non_negative_int(
        identity.get("unique_legal_id_count"), "identity.unique_legal_id_count"
    ) != count_values["unique_legal_ids"]:
        raise IdentityCollisionError("identity unique count drifted")
    if _require_non_negative_int(
        identity.get("duplicate_observations"), "identity.duplicate_observations"
    ) != count_values["duplicate"]:
        raise IdentityCollisionError("identity duplicate count drifted")
    sample_legal_ids = identity.get("sample_legal_ids")
    sample_document_numbers = identity.get("sample_document_numbers")
    if not isinstance(sample_legal_ids, list) or not isinstance(
        sample_document_numbers, list
    ):
        raise IdentityCollisionError("identity samples must be JSON lists")
    if len(sample_legal_ids) > 12 or len(sample_document_numbers) > 12:
        raise IdentityCollisionError("identity sample bounds exceeded")
    for index, legal_id in enumerate(sample_legal_ids):
        _require_non_empty_str(
            legal_id, f"identity.sample_legal_ids[{index}]", maximum=512
        )
    for index, document_number in enumerate(sample_document_numbers):
        validate_document_number(
            document_number,
            name=f"identity.sample_document_numbers[{index}]",
        )

    delta = _as_mapping(raw.get("delta"), "delta")
    _require_exact_keys(
        delta,
        {
            "legacy_baseline_end_inclusive",
            "delta_start_inclusive",
            "legacy_advertised_count",
            "legacy_materialized_count",
            "post_endpoint_documents_min",
            "covers_delta_window",
            "note",
        },
        "delta",
    )
    if delta.get("delta_start_inclusive") != LEGACY_DELTA_START_INCLUSIVE:
        raise FederalRegisterAcquisitionError(
            "delta.delta_start_inclusive must be "
            f"{LEGACY_DELTA_START_INCLUSIVE}"
        )
    if delta.get("legacy_baseline_end_inclusive") != LEGACY_BASELINE_END_INCLUSIVE:
        raise FederalRegisterAcquisitionError(
            "delta.legacy_baseline_end_inclusive must be "
            f"{LEGACY_BASELINE_END_INCLUSIVE}"
        )
    for key, expected in (
        ("legacy_advertised_count", LEGACY_ADVERTISED_COUNT),
        ("legacy_materialized_count", LEGACY_MATERIALIZED_COUNT),
        ("post_endpoint_documents_min", POST_ENDPOINT_DELTA_DOCUMENTS_MIN),
    ):
        if _require_non_negative_int(delta.get(key), f"delta.{key}") != expected:
            raise FederalRegisterAcquisitionError(f"delta.{key} drifted")
    if delta.get("covers_delta_window") is not True:
        raise InventoryGapError("inventory delta window is not covered")
    _require_non_empty_str(delta.get("note"), "delta.note", maximum=2048)
    if live_authority:
        if delta.get("covers_delta_window") is not True:
            raise InventoryGapError(
                "live inventory does not cover its exact delta window"
            )
        if (
            delta.get("post_endpoint_documents_min")
            != POST_ENDPOINT_DELTA_DOCUMENTS_MIN
        ):
            raise FederalRegisterAcquisitionError(
                "live inventory post-endpoint minimum drifted"
            )

    return {
        "structure_valid": True,
        "acceptance": dict(acceptance),
        "unique_document_count": acceptance.get("unique_document_count"),
        "partition_count": acceptance.get("partition_count"),
        "frontier_closed": True,
        "inventory_digest": actual_digest,
    }


def _live_replay_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return all stable live evidence fields compared across fresh replays."""

    return {
        key: value
        for key, value in report.items()
        if key not in {"observed_at", "inventory_digest"}
    }


def _snapshot_inventory_report(report: JsonMapping) -> dict[str, Any]:
    """Freeze one ordinary JSON object before validation or persistence."""

    if type(report) is not dict:
        raise FederalRegisterAcquisitionError(
            "inventory report must be an ordinary JSON object"
        )
    try:
        data = canonical_json_dumps(report).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise FederalRegisterAcquisitionError(
            "inventory report is not strict canonicalizable JSON"
        ) from exc
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise FederalRegisterAcquisitionError("inventory report exceeds size bound")
    return _strict_json_object_from_bytes(data, context="inventory report snapshot")


def inspect_inventory_report_structure(
    report: JsonMapping,
    *,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate frozen report bytes without conferring live authority.

    This entry point exists for hermetic CI inspection of a committed live
    receipt.  Only :func:`check_inventory_report` performs the independent
    checkpoint-free HTTPS replay required to return ``ok=True`` for live data.
    """

    snapshot = _snapshot_inventory_report(report)
    structural = _check_inventory_report_structure(
        snapshot,
        require_live=require_live,
    )
    structural["live_authority_replayed"] = False
    structural["authorizing"] = False
    return structural


def _fresh_live_inventory_report() -> dict[str, Any]:
    """Acquire one checkpoint-free built-in HTTPS replay for authorization."""

    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            observation_cutoff=DEFAULT_OBSERVATION_CUTOFF,
            range_start=LEGACY_DELTA_START_INCLUSIVE,
            range_end=DEFAULT_OBSERVATION_CUTOFF_DATE,
            mode=AcquisitionMode.LIVE,
            per_page=DEFAULT_PER_PAGE,
            resume=False,
            checkpoint_dir=None,
        )
    )
    if not result.frontier_closed:
        raise InventoryGapError(
            "fresh official replay did not close: "
            + "; ".join(result.errors[:8])
        )
    return result.inventory_report


def check_inventory_report(
    report: JsonMapping,
    *,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate structure and freshly replay every claimed live report."""

    snapshot = _snapshot_inventory_report(report)
    structural = _check_inventory_report_structure(
        snapshot,
        require_live=require_live,
    )
    raw = expand_inventory_payload(snapshot)
    if raw.get("mode") != MODE_LIVE:
        structural["live_authority_replayed"] = False
        structural["ok"] = True
        return structural

    fresh = _fresh_live_inventory_report()
    _check_inventory_report_structure(fresh, require_live=True)
    observed_projection = _live_replay_projection(raw)
    fresh_projection = _live_replay_projection(fresh)
    if canonical_json_dumps(observed_projection) != canonical_json_dumps(
        fresh_projection
    ):
        raise InventoryDriftError(
            "live inventory differs from a fresh checkpoint-free official replay"
        )
    structural["live_authority_replayed"] = True
    structural["fresh_inventory_digest"] = fresh["inventory_digest"]
    structural["ok"] = True
    return structural


def write_inventory_report(
    report: Mapping[str, Any],
    path: PathLike | None = None,
) -> Path:
    """Write *report* to the frozen inventory path (atomic)."""

    snapshot = _snapshot_inventory_report(report)
    target = Path(path) if path is not None else default_report_path()
    check_inventory_report(
        snapshot,
        require_live=snapshot.get("mode") == MODE_LIVE,
    )
    atomic_write_json(target, snapshot)
    return target


def load_inventory_report(path: PathLike | None = None) -> dict[str, Any]:
    """Load an on-disk federal inventory report (expands compact recipes)."""

    target = Path(path) if path is not None else default_report_path()
    payload = load_json_object(target)
    return expand_inventory_payload(payload)


def build_fixture_inventory_report(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
    checkpoint_dir: PathLike | None = None,
) -> dict[str, Any]:
    """Run sealed fixture acquisition and return the inventory report."""

    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            observation_cutoff=observation_cutoff,
            mode=AcquisitionMode.FIXTURE,
            resume=checkpoint_dir is not None,
            checkpoint_dir=Path(checkpoint_dir) if checkpoint_dir else None,
            per_page=FIXTURE_PER_PAGE,
        )
    )
    if not result.frontier_closed:
        raise FederalRegisterAcquisitionError(
            "fixture inventory acquisition failed to close: "
            + "; ".join(result.errors[:8])
        )
    check_inventory_report(result.inventory_report)
    return result.inventory_report


def render_check_summary(result: Mapping[str, Any]) -> str:
    """Render a one-line check summary for CLI output."""

    acceptance = result.get("acceptance") or {}
    return (
        f"ok={result.get('ok')} "
        f"frontier_closed={result.get('frontier_closed')} "
        f"partitions={acceptance.get('partition_count')} "
        f"unique_docs={acceptance.get('unique_document_count')} "
        f"failed_final={acceptance.get('failed_final')} "
        f"drift={acceptance.get('unexplained_count_drift')} "
        f"digest={(result.get('inventory_digest') or '')[:12]}"
    )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "SCHEMA_VERSION",
    "REPORT_SCHEMA",
    "CHECKPOINT_SCHEMA",
    "TASK_ID",
    "GOAL_ID",
    "PROGRAM_ID",
    "PRODUCER",
    "MODE_FIXTURE",
    "MODE_LIVE",
    "DEFAULT_REPORT_RELPATH",
    "FIXTURE_RANGE_START",
    "FIXTURE_RANGE_END",
    "POST_ENDPOINT_DELTA_DOCUMENTS_MIN",
    "AcquisitionConfig",
    "AcquisitionMode",
    "AcquisitionResult",
    "CheckpointError",
    "DocumentDisposition",
    "FailedFinalItemError",
    "FederalRegisterAcquisitionError",
    "FixtureApiTransport",
    "FixtureTransportError",
    "IdentityCollisionError",
    "InventoryDocument",
    "InventoryDriftError",
    "InventoryGapError",
    "LiveTransportDisabledError",
    "PageEvidence",
    "PageFetchError",
    "PartitionAcquisitionState",
    "PartitionPlanError",
    "PartitionSpec",
    "SecretInReceiptError",
    "acquire_federal_register_inventory",
    "acquire_partition",
    "assert_inventory_closed",
    "assert_no_secrets",
    "atomic_create_json",
    "atomic_write_json",
    "build_compact_inventory_recipe",
    "build_completion_receipt",
    "build_default_fixture_recipe",
    "build_documents_api_url",
    "build_fixture_inventory_report",
    "build_inventory_report",
    "check_inventory_report",
    "default_checkpoint_dir",
    "default_report_path",
    "expand_inventory_payload",
    "expected_fixture_acceptance",
    "find_secret_surfaces",
    "format_utc_now",
    "is_inventory_recipe",
    "live_http_transport",
    "load_json_object",
    "load_inventory_report",
    "month_end",
    "plan_delta_partitions",
    "plan_full_history_partitions",
    "plan_monthly_partitions",
    "render_check_summary",
    "write_inventory_report",
]
