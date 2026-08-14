"""Coordinate prior state-law evidence and lease only missing live scrapes (OUL-006).

The separate state-laws supervisor may contribute receipts, but those inputs
are untrusted. A receipt is reused only after byte-hash and frontier
verification. Synthetic two-row cohort reports, completion ledgers, fixture
transports, and open or unreplayed frontiers never authorize reuse.

Live jurisdiction leases are exclusive. A foreign in-progress scrape is
waited on rather than duplicated. Missing or invalid jurisdictions are
scheduled exactly once under an Open US Law board lease.

This module performs no network I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    CANONICAL_JURISDICTIONS,
    FORBIDDEN_DEFAULT_JURISDICTIONS,
    CompletenessVerdict,
    evaluate_jurisdiction_receipt,
    extract_body_hash,
    extract_frontier_digest,
    extract_request_hash,
    extract_response_hash,
    is_forbidden_default_jurisdiction,
    normalize_postal_code,
    sha256_text,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-acquisition-leases-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-acquisition-leases@1"
TASK_ID: Final = "OUL-006"
GOAL_ID: Final = "OUL-G010"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_acquisition_coordinator.py"
CODE_VERSION: Final = "1"
SEALED_AT: Final = "2026-08-13T00:00:00Z"
EXPECTED_JURISDICTION_COUNT: Final = 51

OUL_HOLDER: Final = "oul-board"
OUL_HOLDER_BOARD: Final = "open-us-law-reindex-v1"
STATE_LAWS_HOLDER: Final = "state-laws-supervisor"
STATE_LAWS_HOLDER_BOARD: Final = "legal-corpora-reindex-v1"

DEFAULT_LEASE_REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/open_us_law_reindex/acquisition_leases.json"
)
DEFAULT_SOURCE_ADMISSION_RELATIVE_PATH: Final = Path(
    "data/legal/open_us_law/source_admission.json"
)
DEFAULT_PRIOR_COHORT_DIR_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex"
)
DEFAULT_COMPLETED_STATES_BASELINE_RELATIVE_PATH: Final = Path(
    "scripts/ops/legal_data/state_laws_completed_states.baseline.json"
)

TWO_ROW_COUNT: Final = 2
SHA256_HEX_LENGTH: Final = 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_PATH_RE = re.compile(r"(?:/home/|/Users/|C:\\Users\\)")
_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")

ACTION_REUSE: Final = "reuse"
ACTION_SCHEDULE: Final = "schedule_scrape"
ACTION_REPAIR: Final = "repair"
ACTION_WAIT: Final = "wait_live_lease"

STATUS_REUSED: Final = "reused"
STATUS_SCHEDULED: Final = "scheduled"
STATUS_WAIT: Final = "wait"
STATUS_ACTIVE: Final = "active"

LIVE_FOREIGN_STATUSES: Final = frozenset(
    {
        "active",
        "held",
        "in_progress",
        "in-progress",
        "running",
        "leased",
        "live",
        "acquired",
    }
)
REJECTION_SYNTHETIC_TWO_ROW: Final = "synthetic_two_row"
REJECTION_BYTE_VERIFICATION: Final = "byte_verification_failed"
REJECTION_FRONTIER_VERIFICATION: Final = "frontier_verification_failed"
REJECTION_COMPLETENESS: Final = "completeness_oracle_failed"
REJECTION_LEDGER: Final = "untrusted_completion_ledger"
REJECTION_SOURCE_PROJECTION: Final = "source_projection_failed"
REJECTION_MISSING_RECEIPT: Final = "missing_receipt"
REJECTION_FORBIDDEN_JURISDICTION: Final = "forbidden_default_jurisdiction"
REJECTION_FIXTURE: Final = "fixture_or_synthetic_transport"
REJECTION_STALE: Final = "stale_or_conflicting_evidence"
REJECTION_RAW_BYTES_UNCHECKED: Final = "raw_bytes_unchecked"
REJECTION_ZERO_ROW_SUCCESS: Final = "zero_row_success"
REJECTION_PLACEHOLDER: Final = "placeholder_digest"
REJECTION_SAMPLE: Final = "sample_or_cap"
REJECTION_SELF_ASSERTED: Final = "self_asserted_digest"

DEFAULT_COHORT_REPORT_RELATIVE_DIR: Final = Path("docs/reports/open_us_law_reindex")
COHORT_EVIDENCE_SCHEMA_VERSION: Final = "open-us-law-cohort-evidence-v1"
_PLACEHOLDER_DIGEST_TOKENS: Final = (
    "placeholder",
    "sample",
    "dummy",
    "todo",
)
_KNOWN_PLACEHOLDER_DIGESTS: Final = frozenset(
    {
        "0" * 64,
        "f" * 64,
        "a" * 64,
        "deadbeef" * 8,
        "cafebabe" * 8,
    }
)

COHORT_JURISDICTIONS: Final = {
    "A": ("AL", "AK", "AZ", "AR"),
    "B": ("CA", "CO", "CT", "DE"),
    "C": ("FL", "GA", "HI", "ID"),
    "D": ("IL", "IN", "IA", "KS"),
    "E": ("KY", "LA", "ME", "MD"),
    "F": ("MA", "MI", "MN", "MS"),
    "G": ("MO", "MT", "NE", "NV"),
    "H": ("NH", "NJ", "NM", "NY"),
    "I": ("NC", "ND", "OH", "OK"),
    "J": ("OR", "PA", "RI", "SC"),
    "K": ("SD", "TN", "TX", "UT"),
    "L": ("VT", "VA", "WA", "WV"),
    "M": ("WI", "WY", "DC"),
}
COHORT_TASK_IDS: Final = {
    "A": "OUL-009",
    "B": "OUL-010",
    "C": "OUL-011",
    "D": "OUL-012",
    "E": "OUL-013",
    "F": "OUL-014",
    "G": "OUL-015",
    "H": "OUL-016",
    "I": "OUL-017",
    "J": "OUL-018",
    "K": "OUL-019",
    "L": "OUL-020",
    "M": "OUL-021",
}
COHORT_BY_JURISDICTION: Final = {
    code: letter
    for letter, codes in COHORT_JURISDICTIONS.items()
    for code in codes
}

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AcquisitionCoordinationError(ValueError):
    """Fail-closed acquisition coordination failure."""


class DuplicateLeaseError(AcquisitionCoordinationError):
    """Raised when a second live scrape lease would duplicate a jurisdiction."""


class DuplicateScheduleError(AcquisitionCoordinationError):
    """Raised when a missing or invalid jurisdiction would be scheduled twice."""


class LeaseReportError(AcquisitionCoordinationError):
    """Raised when the sealed acquisition-lease report is invalid."""


class LiveEvidenceRequiredError(AcquisitionCoordinationError):
    """Raised when --require-live is set but verified live receipts are absent."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class EvidenceSourceKind(str, Enum):
    """Typed origin of an untrusted prior-evidence item."""

    STATE_LAWS_RECEIPT = "state_laws_receipt"
    STATE_LAWS_COHORT_REPORT = "state_laws_cohort_report"
    COMPLETION_LEDGER = "completion_ledger"
    LIVE_FOREIGN_LEASE = "live_foreign_lease"
    CALLER = "caller"
    MISSING = "missing"


@dataclass(frozen=True)
class ByteVerification:
    """Result of request/response/body hash and optional raw-byte checks."""

    ok: bool
    request_sha256: Optional[str]
    response_sha256: Optional[str]
    admitted_body_sha256: Optional[str]
    replay_matched: bool
    raw_bytes_checked: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "admitted_body_sha256": self.admitted_body_sha256,
            "replay_matched": self.replay_matched,
            "raw_bytes_checked": self.raw_bytes_checked,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FrontierVerification:
    """Result of closed-frontier and frontier-digest replay checks."""

    ok: bool
    frontier_digest_sha256: Optional[str]
    closed: bool
    replay_matched: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "frontier_digest_sha256": self.frontier_digest_sha256,
            "closed": self.closed,
            "replay_matched": self.replay_matched,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReceiptAdmission:
    """Admission decision for one prior state-law receipt or ledger claim."""

    jurisdiction_code: str
    accepted: bool
    source_kind: str
    source_label: str
    rejection_kinds: tuple[str, ...]
    detail: str
    row_count: Optional[int] = None
    byte_verification: Optional[ByteVerification] = None
    frontier_verification: Optional[FrontierVerification] = None
    completeness_kinds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jurisdiction_code": self.jurisdiction_code,
            "accepted": self.accepted,
            "source_kind": self.source_kind,
            "source_label": self.source_label,
            "rejection_kinds": list(self.rejection_kinds),
            "detail": self.detail,
            "row_count": self.row_count,
            "completeness_kinds": list(self.completeness_kinds),
        }
        if self.byte_verification is not None:
            payload["byte_verification"] = self.byte_verification.to_dict()
        if self.frontier_verification is not None:
            payload["frontier_verification"] = self.frontier_verification.to_dict()
        return payload


@dataclass(frozen=True)
class JurisdictionLease:
    """Exclusive live-scrape or reuse lease for one jurisdiction."""

    jurisdiction_code: str
    lease_id: str
    holder: str
    holder_board: str
    status: str
    action: str
    cohort: str
    oul_task_id: str
    reason: str
    acquired_at: str
    expires_at: Optional[str] = None
    prevents_duplicate_scrape: bool = True
    prior_receipt_accepted: bool = False
    byte_verified: bool = False
    frontier_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "acquired_at": self.acquired_at,
            "byte_verified": self.byte_verified,
            "cohort": self.cohort,
            "expires_at": self.expires_at,
            "frontier_verified": self.frontier_verified,
            "holder": self.holder,
            "holder_board": self.holder_board,
            "jurisdiction_code": self.jurisdiction_code,
            "lease_id": self.lease_id,
            "oul_task_id": self.oul_task_id,
            "prevents_duplicate_scrape": self.prevents_duplicate_scrape,
            "prior_receipt_accepted": self.prior_receipt_accepted,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass
class LeaseRegistry:
    """In-memory exclusive lease table. One live scrape lease per code."""

    leases: dict[str, JurisdictionLease] = field(default_factory=dict)
    duplicate_attempts: int = 0

    def get(self, code: str) -> Optional[JurisdictionLease]:
        return self.leases.get(_normalize_code(code, allow_forbidden=True))

    def acquire(self, lease: JurisdictionLease) -> JurisdictionLease:
        code = lease.jurisdiction_code
        existing = self.leases.get(code)
        if existing is None:
            self.leases[code] = lease
            return lease
        if (
            existing.holder == lease.holder
            and existing.action == lease.action
            and existing.lease_id == lease.lease_id
        ):
            return existing
        self.duplicate_attempts += 1
        raise DuplicateLeaseError(
            f"live jurisdiction lease already held for {code}: "
            f"holder={existing.holder} action={existing.action}; "
            f"refusing duplicate holder={lease.holder} action={lease.action}"
        )

    def as_tuple(self) -> tuple[JurisdictionLease, ...]:
        return tuple(
            self.leases[code]
            for code in CANONICAL_JURISDICTION_ORDER
            if code in self.leases
        )


@dataclass(frozen=True)
class CoordinationPlan:
    """Exact-51 lease and schedule plan."""

    leases: tuple[JurisdictionLease, ...]
    admissions: tuple[ReceiptAdmission, ...]
    scheduled_codes: tuple[str, ...]
    reused_codes: tuple[str, ...]
    waiting_codes: tuple[str, ...]
    repair_codes: tuple[str, ...]
    duplicate_lease_attempts: int
    duplicate_schedule_attempts: int

    def lease_for(self, code: str) -> JurisdictionLease:
        needle = str(code).strip().upper()
        for item in self.leases:
            if item.jurisdiction_code == needle:
                return item
        raise AcquisitionCoordinationError(f"no lease recorded for {needle}")

    def to_summary(self) -> dict[str, int]:
        return {
            ACTION_REUSE: len(self.reused_codes),
            ACTION_SCHEDULE: len(self.scheduled_codes)
            - len(self.repair_codes),
            ACTION_REPAIR: len(self.repair_codes),
            ACTION_WAIT: len(self.waiting_codes),
        }


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    """Return the repository root that contains ``data/legal``."""

    return Path(__file__).resolve().parents[3]


def default_lease_report_path(repo_root: Optional[PathLike] = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_LEASE_REPORT_RELATIVE_PATH).resolve()


def default_cohort_report_path(
    cohort: str,
    repo_root: Optional[PathLike] = None,
) -> Path:
    """Return the declared Open US Law cohort evidence path (not legal_corpora)."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    letter = str(cohort or "").strip().upper()
    return (root / DEFAULT_COHORT_REPORT_RELATIVE_DIR / f"cohort_{letter}.json").resolve()


def is_cohort_evidence_payload(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("schema_version") == COHORT_EVIDENCE_SCHEMA_VERSION
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def encode_acquisition_leases(payload: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(payload)


def _normalize_sha256(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if _SHA256_RE.fullmatch(text):
        return text
    return None


def _normalize_code(value: Any, *, allow_forbidden: bool = False) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise AcquisitionCoordinationError("jurisdiction code is required")
    if is_forbidden_default_jurisdiction(text):
        if allow_forbidden:
            return text
        raise AcquisitionCoordinationError(
            f"jurisdiction {text} is forbidden in the exact-51 default set"
        )
    if text not in CANONICAL_JURISDICTIONS:
        raise AcquisitionCoordinationError(
            f"jurisdiction {text} is not a member of the exact-51 set"
        )
    return normalize_postal_code(text)


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _row_count(payload: Mapping[str, Any]) -> Optional[int]:
    for key in ("row_count", "statutes_count", "fetched"):
        counted = _as_int(payload.get(key))
        if counted is not None:
            return counted
    disposition = payload.get("disposition")
    if isinstance(disposition, Mapping):
        for key in ("fetched", "discovered"):
            counted = _as_int(disposition.get(key))
            if counted is not None:
                return counted
    return None


def _frontier_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    frontier = payload.get("frontier")
    return frontier if isinstance(frontier, Mapping) else {}


def _replay_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    replay = payload.get("replay")
    return replay if isinstance(replay, Mapping) else {}


def cohort_letter(code: str) -> str:
    normalized = str(code).strip().upper()
    letter = COHORT_BY_JURISDICTION.get(normalized)
    if letter is None:
        raise AcquisitionCoordinationError(
            f"jurisdiction {normalized} has no OUL scrape cohort"
        )
    return letter


def cohort_task_id(code: str) -> str:
    return COHORT_TASK_IDS[cohort_letter(code)]


def cohort_codes(letter: str) -> tuple[str, ...]:
    key = str(letter or "").strip().upper()
    if key not in COHORT_JURISDICTIONS:
        raise AcquisitionCoordinationError(
            f"unknown cohort {letter!r}; expected one of {sorted(COHORT_JURISDICTIONS)}"
        )
    return COHORT_JURISDICTIONS[key]


def lease_id_for(code: str, holder: str, action: str) -> str:
    material = f"{PROGRAM_ID}|{TASK_ID}|{code}|{holder}|{action}"
    return f"oul-006:{code}:{sha256_text(material)[:16]}"


def find_secret_surfaces(value: Any) -> list[str]:
    """Return secret-looking surfaces that must not enter a sealed report."""

    serialized = value if isinstance(value, str) else json.dumps(value, default=str)
    hits: list[str] = []
    if _SECRET_PATH_RE.search(serialized):
        hits.append("absolute_home_path")
    if _HF_TOKEN_RE.search(serialized):
        hits.append("huggingface_token")
    if _BEARER_RE.search(serialized):
        hits.append("bearer_token")
    lowered = serialized.lower()
    if "api_key" in lowered and "api_key" in serialized:
        if re.search(r"api_key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{8,}", serialized):
            hits.append("api_key")
    return hits


def assert_no_secrets(value: Any) -> None:
    hits = find_secret_surfaces(value)
    if hits:
        raise LeaseReportError(
            "acquisition lease report contains secret material: " + ",".join(hits)
        )


# ---------------------------------------------------------------------------
# Two-row / ledger / transport classifiers
# ---------------------------------------------------------------------------


def is_synthetic_two_row_report(receipt: Mapping[str, Any]) -> bool:
    """Return True for the known two-row fixture / synthetic success shape.

    No exact-51 jurisdiction has a two-section official code. Success claims
    whose fetched, row, statute, and frontier unit counts are all ≤ 2 are
    treated as the state-laws supervisor's synthetic two-row reports.
    """

    if not isinstance(receipt, Mapping):
        return False
    disposition = receipt.get("disposition")
    disposition_map = disposition if isinstance(disposition, Mapping) else {}
    frontier = _frontier_block(receipt)
    counts = [
        _as_int(receipt.get("row_count")),
        _as_int(receipt.get("statutes_count")),
        _as_int(receipt.get("fetched")),
        _as_int(disposition_map.get("fetched")),
        _as_int(disposition_map.get("discovered")),
        _as_int(frontier.get("expected_index_units")),
        _as_int(frontier.get("visited_index_units")),
    ]
    present = [item for item in counts if item is not None]
    if not present:
        return False
    two_row_markers = [
        item
        for item in (
            _as_int(receipt.get("row_count")),
            _as_int(receipt.get("statutes_count")),
            _as_int(receipt.get("fetched")),
            _as_int(disposition_map.get("fetched")),
            _as_int(disposition_map.get("discovered")),
        )
        if item == TWO_ROW_COUNT
    ]
    if not two_row_markers:
        return False
    return max(present) <= TWO_ROW_COUNT


def is_completion_ledger_claim(payload: Mapping[str, Any]) -> bool:
    """Return True for a status/count ledger row with no scrape receipt."""

    if not isinstance(payload, Mapping):
        return False
    if payload.get("ledger_only") is True:
        return True
    has_frontier = isinstance(payload.get("frontier"), Mapping)
    has_hashes = isinstance(payload.get("hashes"), Mapping) or any(
        payload.get(key) for key in ("request_sha256", "response_sha256", "admitted_body_sha256")
    )
    has_replay = isinstance(payload.get("replay"), Mapping)
    status = str(payload.get("status") or payload.get("completion_mode") or "").strip()
    count = _as_int(payload.get("statutes_count"))
    if status and count is not None and not has_frontier and not has_hashes and not has_replay:
        return True
    return False


def is_placeholder_digest(value: Any) -> bool:
    """Return True for empty, non-hex, repeated, or token placeholder digests."""

    if value is None:
        return True
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not text or not _SHA256_RE.fullmatch(text):
        return True
    if len(set(text)) == 1:
        return True
    if text in _KNOWN_PLACEHOLDER_DIGESTS:
        return True
    return any(token in text for token in _PLACEHOLDER_DIGEST_TOKENS)


def is_placeholder_cid(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text or not text.startswith("b") or len(text) < 21:
        return True
    return any(token in text for token in _PLACEHOLDER_DIGEST_TOKENS)


def _has_sample_or_cap(receipt: Mapping[str, Any]) -> bool:
    if receipt.get("sample_cap") not in {None, 0, False}:
        return True
    if receipt.get("runtime_caps") not in {None, 0, False} and receipt.get("runtime_caps") != {}:
        return True
    mode = str(receipt.get("mode") or "full").strip().lower()
    return mode not in {"", "full", "uncapped"}


def _is_zero_row_success(receipt: Mapping[str, Any]) -> bool:
    status = str(receipt.get("status") or "").strip().lower()
    if status not in {"success", "complete", "ok", "passed"}:
        return False
    counts: list[int] = []
    for key in ("row_count", "statutes_count", "fetched"):
        counted = _as_int(receipt.get(key))
        if counted is not None:
            counts.append(counted)
    disposition = receipt.get("disposition")
    if isinstance(disposition, Mapping):
        counted = _as_int(disposition.get("fetched"))
        if counted is not None:
            counts.append(counted)
    return bool(counts) and min(counts) <= 0


def _has_placeholder_identity(receipt: Mapping[str, Any]) -> bool:
    hashes = receipt.get("hashes") if isinstance(receipt.get("hashes"), Mapping) else receipt
    for key in ("request_sha256", "response_sha256", "admitted_body_sha256"):
        value = hashes.get(key) if isinstance(hashes, Mapping) else None
        if value and is_placeholder_digest(value):
            return True
    cids = receipt.get("cids")
    if isinstance(cids, Mapping):
        for value in cids.values():
            if is_placeholder_cid(value):
                return True
    return False


def _strict_live_admission_gates(
    receipt: Mapping[str, Any],
    byte_verdict: ByteVerification,
) -> tuple[list[str], list[str]]:
    """Extra fail-closed gates applied only to otherwise-accepted receipts."""

    kinds: list[str] = []
    details: list[str] = []
    if not byte_verdict.raw_bytes_checked:
        kinds.append(REJECTION_RAW_BYTES_UNCHECKED)
        details.append("raw_bytes_checked=false is not reusable evidence")
        kinds.append(REJECTION_SELF_ASSERTED)
        details.append("declared hashes are self-asserted without retained bytes")
    if _is_zero_row_success(receipt):
        kinds.append(REJECTION_ZERO_ROW_SUCCESS)
        details.append("zero-row success is not reusable evidence")
    if _has_sample_or_cap(receipt):
        kinds.append(REJECTION_SAMPLE)
        details.append("sample or runtime cap cannot be reused")
    if _has_placeholder_identity(receipt):
        kinds.append(REJECTION_PLACEHOLDER)
        details.append("placeholder hashes or CIDs cannot be reused")
    return kinds, details


def _transport_is_fixture(receipt: Mapping[str, Any]) -> bool:
    transport = receipt.get("transport")
    kind = ""
    if isinstance(transport, str):
        kind = transport.strip().lower().replace("-", "_")
    elif isinstance(transport, Mapping):
        kind = str(transport.get("kind") or transport.get("type") or "").strip().lower()
        if transport.get("fixture") is True or transport.get("synthetic") is True:
            return True
    if receipt.get("synthetic") is True or receipt.get("synthetic_receipt") is True:
        return True
    if receipt.get("fixture_transport") is True:
        return True
    return kind in {
        "fixture",
        "fixtures",
        "mock",
        "mocked",
        "synthetic",
        "cassette",
        "vcr",
        "recorded_fixture",
        "golden",
        "stub",
        "unit_fixture",
    }


# ---------------------------------------------------------------------------
# Byte and frontier verification
# ---------------------------------------------------------------------------


def verify_receipt_bytes(
    receipt: Mapping[str, Any],
    *,
    request_bytes: Optional[bytes] = None,
    response_bytes: Optional[bytes] = None,
    body_bytes: Optional[bytes] = None,
) -> ByteVerification:
    """Verify request/response/admitted-body hashes, and raw bytes when given."""

    if not isinstance(receipt, Mapping):
        return ByteVerification(
            ok=False,
            request_sha256=None,
            response_sha256=None,
            admitted_body_sha256=None,
            replay_matched=False,
            raw_bytes_checked=False,
            detail="receipt is not an object",
        )
    request_h = extract_request_hash(receipt)
    response_h = extract_response_hash(receipt)
    body_h = extract_body_hash(receipt)
    missing = [
        name
        for name, value in (
            ("request_sha256", request_h),
            ("response_sha256", response_h),
            ("admitted_body_sha256", body_h),
        )
        if not value
    ]
    if missing:
        return ByteVerification(
            ok=False,
            request_sha256=request_h,
            response_sha256=response_h,
            admitted_body_sha256=body_h,
            replay_matched=False,
            raw_bytes_checked=False,
            detail="missing replayable hashes: " + ",".join(missing),
        )

    replay = _replay_block(receipt)
    if not replay:
        return ByteVerification(
            ok=False,
            request_sha256=request_h,
            response_sha256=response_h,
            admitted_body_sha256=body_h,
            replay_matched=False,
            raw_bytes_checked=False,
            detail="replay block required for byte verification",
        )
    replay_request = _normalize_sha256(
        replay.get("request_sha256") or replay.get("request_hash")
    )
    replay_response = _normalize_sha256(
        replay.get("response_sha256")
        or replay.get("second_response_hash")
        or replay.get("response_hash")
        or replay.get("content_digest")
    )
    replay_body = _normalize_sha256(
        replay.get("admitted_body_sha256")
        or replay.get("body_hash")
        or replay.get("content_digest")
    )
    if not replay_request or not replay_response or not replay_body:
        return ByteVerification(
            ok=False,
            request_sha256=request_h,
            response_sha256=response_h,
            admitted_body_sha256=body_h,
            replay_matched=False,
            raw_bytes_checked=False,
            detail="replay block missing request/response/body hashes",
        )
    mismatches: list[str] = []
    if replay_request != request_h:
        mismatches.append("request_sha256")
    if replay_response != response_h:
        mismatches.append("response_sha256")
    if replay_body != body_h:
        mismatches.append("admitted_body_sha256")
    if mismatches:
        return ByteVerification(
            ok=False,
            request_sha256=request_h,
            response_sha256=response_h,
            admitted_body_sha256=body_h,
            replay_matched=False,
            raw_bytes_checked=False,
            detail="replay hashes differ from declared hashes: " + ",".join(mismatches),
        )

    raw_checked = False
    provided = (
        ("request", request_bytes, request_h),
        ("response", response_bytes, response_h),
        ("admitted_body", body_bytes, body_h),
    )
    for label, raw, expected in provided:
        if raw is None:
            continue
        raw_checked = True
        digest = sha256_bytes(raw)
        if digest != expected:
            return ByteVerification(
                ok=False,
                request_sha256=request_h,
                response_sha256=response_h,
                admitted_body_sha256=body_h,
                replay_matched=True,
                raw_bytes_checked=True,
                detail=f"{label} bytes hash {digest} != {expected}",
            )

    for key in ("admitted_body", "body", "body_text"):
        embedded = receipt.get(key)
        if isinstance(embedded, (bytes, bytearray)):
            raw_checked = True
            digest = sha256_bytes(bytes(embedded))
            if digest != body_h:
                return ByteVerification(
                    ok=False,
                    request_sha256=request_h,
                    response_sha256=response_h,
                    admitted_body_sha256=body_h,
                    replay_matched=True,
                    raw_bytes_checked=True,
                    detail=f"embedded {key} bytes hash {digest} != {body_h}",
                )
        elif isinstance(embedded, str) and embedded and key != "body_text":
            raw_checked = True
            digest = sha256_bytes(embedded.encode("utf-8"))
            if digest != body_h:
                return ByteVerification(
                    ok=False,
                    request_sha256=request_h,
                    response_sha256=response_h,
                    admitted_body_sha256=body_h,
                    replay_matched=True,
                    raw_bytes_checked=True,
                    detail=f"embedded {key} bytes hash {digest} != {body_h}",
                )

    return ByteVerification(
        ok=True,
        request_sha256=request_h,
        response_sha256=response_h,
        admitted_body_sha256=body_h,
        replay_matched=True,
        raw_bytes_checked=raw_checked,
        detail="request, response, and admitted-body hashes replay",
    )


def verify_receipt_frontier(receipt: Mapping[str, Any]) -> FrontierVerification:
    """Verify closed bundle/pagination frontier and replayed frontier digest."""

    if not isinstance(receipt, Mapping):
        return FrontierVerification(
            ok=False,
            frontier_digest_sha256=None,
            closed=False,
            replay_matched=False,
            detail="receipt is not an object",
        )
    frontier = receipt.get("frontier")
    if not isinstance(frontier, Mapping):
        return FrontierVerification(
            ok=False,
            frontier_digest_sha256=None,
            closed=False,
            replay_matched=False,
            detail="receipt missing frontier block",
        )
    digest = extract_frontier_digest(receipt)
    closed = frontier.get("closed") is True
    enumerator_closed = frontier.get("enumerator_closed")
    bundle_closed = frontier.get("bundle_closed") is True
    pagination_closed = frontier.get("pagination_closed") is True
    unvisited = [
        str(item)
        for item in (frontier.get("unvisited_continuation_links") or [])
        if str(item).strip()
    ]
    remaining = [
        str(item)
        for item in (
            frontier.get("remaining_bundle_members")
            or frontier.get("unvisited_bundle_members")
            or []
        )
        if str(item).strip()
    ]
    method = str(frontier.get("method") or frontier.get("frontier_method") or "").strip().lower()
    closed_via_method = bundle_closed or pagination_closed
    if method in {"bundle", "official_bundle"}:
        closed_via_method = bundle_closed
    elif method in {"pagination", "toc", "continuation", "page"}:
        closed_via_method = pagination_closed or (
            closed and enumerator_closed is True
        )
    elif method in {"bundle_and_pagination", "both"}:
        closed_via_method = bundle_closed and pagination_closed
    elif closed and enumerator_closed is True:
        closed_via_method = True

    reasons: list[str] = []
    if not digest:
        reasons.append("frontier_digest_sha256 missing")
    if not closed:
        reasons.append("frontier.closed is not true")
    if enumerator_closed is False:
        reasons.append("frontier.enumerator_closed is false")
    if not closed_via_method:
        reasons.append("neither bundle nor pagination frontier is closed")
    if unvisited:
        reasons.append("unvisited continuation links remain")
    if remaining:
        reasons.append("remaining bundle members remain")

    replay = _replay_block(receipt)
    replay_digest = _normalize_sha256(
        replay.get("frontier_digest_sha256")
        or replay.get("second_frontier_digest")
        or replay.get("first_frontier_digest")
    )
    first_digest = _normalize_sha256(replay.get("first_frontier_digest") or digest)
    replay_matched = bool(digest and replay_digest and first_digest == replay_digest == digest)
    if replay and replay.get("closed") is False:
        reasons.append("replay.closed is false")
        replay_matched = False
    if digest and replay and not replay_digest:
        reasons.append("replay frontier digest missing")
    if digest and replay_digest and replay_digest != digest:
        reasons.append(
            f"replay frontier digest {replay_digest} != {digest}"
        )
        replay_matched = False
    if first_digest and replay_digest and first_digest != replay_digest:
        reasons.append("first and second frontier digests differ")
        replay_matched = False
    if not replay:
        reasons.append("replay block required for frontier verification")

    ok = not reasons and replay_matched and closed
    return FrontierVerification(
        ok=ok,
        frontier_digest_sha256=digest,
        closed=closed and closed_via_method and not unvisited and not remaining,
        replay_matched=replay_matched,
        detail="frontier closed and replayed" if ok else "; ".join(reasons),
    )


def verify_source_projection(
    receipt: Mapping[str, Any],
    *,
    admission_row: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return a rejection detail when the official source projection is wrong."""

    if receipt.get("official_source") is False:
        return "official_source is false"
    authority = str(
        receipt.get("source_authority_class") or receipt.get("authority_class") or ""
    ).strip().lower()
    if authority in {"secondary", "unofficial", "mirror"}:
        return f"source_authority_class={authority} is not official"
    domain = str(receipt.get("source_domain") or "").strip().lower().strip(".")
    if admission_row and domain:
        authority_block = admission_row.get("official_authority")
        allowed: list[str] = []
        if isinstance(authority_block, Mapping):
            raw_allowed = authority_block.get("allowed_domains") or []
            if isinstance(raw_allowed, Sequence) and not isinstance(raw_allowed, (str, bytes)):
                allowed = [str(item).strip().lower().strip(".") for item in raw_allowed if str(item).strip()]
        if allowed and not any(
            domain == item or domain.endswith("." + item) for item in allowed
        ):
            return f"source_domain {domain} is outside allowed official hosts"
    return None


# ---------------------------------------------------------------------------
# Receipt admission
# ---------------------------------------------------------------------------


def evaluate_prior_receipt(
    receipt: Mapping[str, Any],
    *,
    source_kind: str = EvidenceSourceKind.CALLER.value,
    source_label: str = "caller",
    request_bytes: Optional[bytes] = None,
    response_bytes: Optional[bytes] = None,
    body_bytes: Optional[bytes] = None,
    admission_row: Optional[Mapping[str, Any]] = None,
) -> ReceiptAdmission:
    """Admit a prior state-law receipt only after byte and frontier verification."""

    if not isinstance(receipt, Mapping):
        return ReceiptAdmission(
            jurisdiction_code="",
            accepted=False,
            source_kind=source_kind,
            source_label=source_label,
            rejection_kinds=(REJECTION_MISSING_RECEIPT,),
            detail="prior evidence is not an object",
        )
    raw_code = receipt.get("jurisdiction") or receipt.get("jurisdiction_code")
    raw_text = str(raw_code or "").strip().upper()
    if raw_text and is_forbidden_default_jurisdiction(raw_text):
        return ReceiptAdmission(
            jurisdiction_code=raw_text,
            accepted=False,
            source_kind=source_kind,
            source_label=source_label,
            rejection_kinds=(REJECTION_FORBIDDEN_JURISDICTION,),
            detail=f"{raw_text} is forbidden in the exact-51 default set",
            row_count=_row_count(receipt),
        )
    try:
        code = _normalize_code(raw_code)
    except AcquisitionCoordinationError as exc:
        return ReceiptAdmission(
            jurisdiction_code=raw_text,
            accepted=False,
            source_kind=source_kind,
            source_label=source_label,
            rejection_kinds=(REJECTION_MISSING_RECEIPT,),
            detail=str(exc),
            row_count=_row_count(receipt),
        )

    kinds: list[str] = []
    details: list[str] = []
    if is_synthetic_two_row_report(receipt):
        kinds.append(REJECTION_SYNTHETIC_TWO_ROW)
        details.append("synthetic two-row report is not reusable evidence")
    if is_completion_ledger_claim(receipt):
        kinds.append(REJECTION_LEDGER)
        details.append("completion ledger status/count is not a verified receipt")
    if _transport_is_fixture(receipt):
        kinds.append(REJECTION_FIXTURE)
        details.append("fixture or synthetic transport cannot be reused")

    byte_verdict = verify_receipt_bytes(
        receipt,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        body_bytes=body_bytes,
    )
    if not byte_verdict.ok:
        kinds.append(REJECTION_BYTE_VERIFICATION)
        details.append(byte_verdict.detail)

    frontier_verdict = verify_receipt_frontier(receipt)
    if not frontier_verdict.ok:
        kinds.append(REJECTION_FRONTIER_VERIFICATION)
        details.append(frontier_verdict.detail)

    projection = verify_source_projection(receipt, admission_row=admission_row)
    if projection:
        kinds.append(REJECTION_SOURCE_PROJECTION)
        details.append(projection)
    if _is_zero_row_success(receipt):
        kinds.append(REJECTION_ZERO_ROW_SUCCESS)
        details.append("zero-row success is not reusable evidence")
    if _has_sample_or_cap(receipt):
        kinds.append(REJECTION_SAMPLE)
        details.append("sample or runtime cap cannot be reused")
    if _has_placeholder_identity(receipt):
        kinds.append(REJECTION_PLACEHOLDER)
        details.append("placeholder hashes or CIDs cannot be reused")
    if (
        not kinds
        and byte_verdict.ok
        and not byte_verdict.raw_bytes_checked
    ):
        extra_kinds, extra_details = _strict_live_admission_gates(receipt, byte_verdict)
        extra_kinds = [
            kind
            for kind in extra_kinds
            if kind
            in {REJECTION_RAW_BYTES_UNCHECKED, REJECTION_SELF_ASSERTED}
        ]
        extra_details = [
            detail
            for detail in extra_details
            if "raw_bytes_checked" in detail or "self-asserted" in detail
        ]
        kinds.extend(extra_kinds)
        details.extend(extra_details)

    completeness: CompletenessVerdict | None = None
    completeness_kinds: tuple[str, ...] = ()
    if not is_completion_ledger_claim(receipt):
        completeness = evaluate_jurisdiction_receipt(
            receipt, case_id=f"prior-{code}"
        )
        completeness_kinds = completeness.kinds
        if not completeness.complete:
            kinds.append(REJECTION_COMPLETENESS)
            details.append(
                "completeness oracle rejected receipt: "
                + ",".join(completeness.kinds) or "incomplete"
            )

    accepted = not kinds and byte_verdict.ok and frontier_verdict.ok
    if accepted and completeness is not None and not completeness.complete:
        accepted = False
    if accepted:
        detail = "byte and frontier verification passed; receipt reusable"
    else:
        detail = "; ".join(details) if details else "prior evidence rejected"
    return ReceiptAdmission(
        jurisdiction_code=code,
        accepted=accepted,
        source_kind=source_kind,
        source_label=source_label,
        rejection_kinds=tuple(dict.fromkeys(kinds)),
        detail=detail,
        row_count=_row_count(receipt),
        byte_verification=byte_verdict,
        frontier_verification=frontier_verdict,
        completeness_kinds=completeness_kinds,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _load_json_object(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_source_admission_index(
    path: Optional[PathLike] = None,
) -> dict[str, Mapping[str, Any]]:
    report_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else repository_root() / DEFAULT_SOURCE_ADMISSION_RELATIVE_PATH
    )
    payload = _load_json_object(report_path)
    if payload is None:
        return {}
    rows = payload.get("jurisdictions")
    if not isinstance(rows, list):
        return {}
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("jurisdiction_code") or "").strip().upper()
        if code in CANONICAL_JURISDICTIONS:
            indexed[code] = row
    return indexed


def discover_state_laws_cohort_receipts(
    repo_root: Optional[PathLike] = None,
) -> list[tuple[dict[str, Any], str]]:
    """Load untrusted jurisdiction receipts from state-laws cohort reports."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    directory = (root / DEFAULT_PRIOR_COHORT_DIR_RELATIVE_PATH).resolve()
    found: list[tuple[dict[str, Any], str]] = []
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("cohort_*.json")):
        payload = _load_json_object(path)
        if payload is None:
            continue
        relative = path.relative_to(root).as_posix() if root in path.parents or path == root else path.name
        receipts = payload.get("jurisdiction_receipts")
        if isinstance(receipts, Mapping):
            for code, row in receipts.items():
                if not isinstance(row, Mapping):
                    continue
                item = dict(row)
                item.setdefault("jurisdiction", str(code).strip().upper())
                found.append((item, f"{relative}:{code}"))
        elif isinstance(receipts, list):
            for row in receipts:
                if isinstance(row, Mapping):
                    found.append((dict(row), relative))
    return found


def discover_completion_ledger_claims(
    repo_root: Optional[PathLike] = None,
) -> list[tuple[dict[str, Any], str]]:
    """Load untrusted completion-ledger rows (status/count only)."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    path = (root / DEFAULT_COMPLETED_STATES_BASELINE_RELATIVE_PATH).resolve()
    payload = _load_json_object(path)
    if payload is None:
        return []
    relative = (
        path.relative_to(root).as_posix()
        if root in path.parents or path == root
        else path.name
    )
    states = payload.get("states")
    if not isinstance(states, Mapping):
        return []
    found: list[tuple[dict[str, Any], str]] = []
    for code, row in states.items():
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        item["jurisdiction"] = str(code).strip().upper()
        item["ledger_only"] = True
        found.append((item, f"{relative}:{code}"))
    return found


def discover_live_foreign_leases(
    payloads: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Normalize caller-supplied live foreign leases. Default is empty."""

    found: list[dict[str, Any]] = []
    for item in payloads or ():
        if not isinstance(item, Mapping):
            continue
        code = str(
            item.get("jurisdiction_code") or item.get("jurisdiction") or ""
        ).strip().upper()
        if code not in CANONICAL_JURISDICTIONS:
            continue
        found.append(
            {
                "jurisdiction_code": code,
                "holder": str(item.get("holder") or STATE_LAWS_HOLDER),
                "holder_board": str(
                    item.get("holder_board") or STATE_LAWS_HOLDER_BOARD
                ),
                "status": str(item.get("status") or STATUS_ACTIVE).strip().lower(),
                "acquired_at": str(item.get("acquired_at") or SEALED_AT),
                "expires_at": item.get("expires_at"),
                "lease_id": str(
                    item.get("lease_id")
                    or lease_id_for(code, str(item.get("holder") or STATE_LAWS_HOLDER), ACTION_WAIT)
                ),
            }
        )
    return found


# ---------------------------------------------------------------------------
# Coordination / leasing
# ---------------------------------------------------------------------------


def unique_schedule(codes: Sequence[str]) -> tuple[tuple[str, ...], int]:
    """Return codes in first-seen order and the number of dropped duplicates."""

    ordered: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for raw in codes:
        code = str(raw).strip().upper()
        if not code:
            continue
        if code in seen:
            duplicates += 1
            continue
        seen.add(code)
        ordered.append(code)
    return tuple(ordered), duplicates


def require_scheduled_exactly_once(codes: Sequence[str]) -> tuple[str, ...]:
    """Return codes or raise if any jurisdiction would be scheduled twice."""

    ordered, duplicates = unique_schedule(codes)
    if duplicates:
        raise DuplicateScheduleError(
            f"missing or invalid jurisdictions must be scheduled exactly once; "
            f"{duplicates} duplicate schedule attempt(s)"
        )
    return ordered


def _foreign_lease_is_live(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    if status not in LIVE_FOREIGN_STATUSES:
        return False
    expires = item.get("expires_at")
    if expires in {None, "", "null"}:
        return True
    # Sealed coordination does not consult wall-clock time. An explicit
    # expires_at in the past relative to SEALED_AT is treated as expired.
    return str(expires) >= SEALED_AT


def _build_lease(
    *,
    code: str,
    holder: str,
    holder_board: str,
    action: str,
    status: str,
    reason: str,
    prior_receipt_accepted: bool,
    byte_verified: bool,
    frontier_verified: bool,
    expires_at: Optional[str] = None,
    lease_id: Optional[str] = None,
) -> JurisdictionLease:
    return JurisdictionLease(
        jurisdiction_code=code,
        lease_id=lease_id or lease_id_for(code, holder, action),
        holder=holder,
        holder_board=holder_board,
        status=status,
        action=action,
        cohort=cohort_letter(code),
        oul_task_id=cohort_task_id(code),
        reason=reason,
        acquired_at=SEALED_AT,
        expires_at=expires_at,
        prevents_duplicate_scrape=True,
        prior_receipt_accepted=prior_receipt_accepted,
        byte_verified=byte_verified,
        frontier_verified=frontier_verified,
    )


def coordinate_jurisdictions(
    *,
    receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ledger_claims: Optional[Mapping[str, Mapping[str, Any]]] = None,
    live_foreign_leases: Optional[Sequence[Mapping[str, Any]]] = None,
    receipt_sources: Optional[Mapping[str, tuple[str, str]]] = None,
    request_bytes: Optional[Mapping[str, bytes]] = None,
    response_bytes: Optional[Mapping[str, bytes]] = None,
    body_bytes: Optional[Mapping[str, bytes]] = None,
    admission_index: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> CoordinationPlan:
    """Build the exclusive lease plan for the exact-51 set.

    Verified receipts are reused. Live foreign leases are waited on.
    Everything else is scheduled exactly once.
    """

    registry = LeaseRegistry()
    admissions: list[ReceiptAdmission] = []
    accepted: dict[str, ReceiptAdmission] = {}
    rejected_by_code: dict[str, list[ReceiptAdmission]] = {}
    admission_index = admission_index or {}
    receipt_sources = receipt_sources or {}
    request_bytes = request_bytes or {}
    response_bytes = response_bytes or {}
    body_bytes = body_bytes or {}

    for code, receipt in (receipts or {}).items():
        source_kind, source_label = receipt_sources.get(
            str(code).strip().upper(),
            (EvidenceSourceKind.CALLER.value, "caller"),
        )
        admission = evaluate_prior_receipt(
            receipt,
            source_kind=source_kind,
            source_label=source_label,
            request_bytes=request_bytes.get(str(code).strip().upper()),
            response_bytes=response_bytes.get(str(code).strip().upper()),
            body_bytes=body_bytes.get(str(code).strip().upper()),
            admission_row=admission_index.get(str(code).strip().upper()),
        )
        admissions.append(admission)
        if admission.accepted:
            accepted[admission.jurisdiction_code] = admission
        elif admission.jurisdiction_code in CANONICAL_JURISDICTIONS:
            rejected_by_code.setdefault(admission.jurisdiction_code, []).append(admission)

    for code, claim in (ledger_claims or {}).items():
        admission = evaluate_prior_receipt(
            claim,
            source_kind=EvidenceSourceKind.COMPLETION_LEDGER.value,
            source_label=f"completion_ledger:{code}",
            admission_row=admission_index.get(str(code).strip().upper()),
        )
        admissions.append(admission)
        if admission.jurisdiction_code in CANONICAL_JURISDICTIONS and not admission.accepted:
            rejected_by_code.setdefault(admission.jurisdiction_code, []).append(admission)

    foreign_by_code: dict[str, dict[str, Any]] = {}
    for item in discover_live_foreign_leases(live_foreign_leases):
        if _foreign_lease_is_live(item):
            foreign_by_code[item["jurisdiction_code"]] = item

    scheduled: list[str] = []
    reused: list[str] = []
    waiting: list[str] = []
    repair: list[str] = []

    for code in CANONICAL_JURISDICTION_ORDER:
        if code in accepted:
            admission = accepted[code]
            byte_ok = bool(admission.byte_verification and admission.byte_verification.ok)
            frontier_ok = bool(
                admission.frontier_verification and admission.frontier_verification.ok
            )
            registry.acquire(
                _build_lease(
                    code=code,
                    holder=OUL_HOLDER,
                    holder_board=OUL_HOLDER_BOARD,
                    action=ACTION_REUSE,
                    status=STATUS_REUSED,
                    reason=(
                        "prior state-laws receipt accepted after byte and "
                        "frontier verification"
                    ),
                    prior_receipt_accepted=True,
                    byte_verified=byte_ok,
                    frontier_verified=frontier_ok,
                )
            )
            reused.append(code)
            continue

        foreign = foreign_by_code.get(code)
        if foreign is not None:
            registry.acquire(
                _build_lease(
                    code=code,
                    holder=str(foreign["holder"]),
                    holder_board=str(foreign["holder_board"]),
                    action=ACTION_WAIT,
                    status=STATUS_WAIT,
                    reason=(
                        "live jurisdiction lease held by "
                        f"{foreign['holder']}; OUL waits and will not duplicate "
                        "the scrape"
                    ),
                    prior_receipt_accepted=False,
                    byte_verified=False,
                    frontier_verified=False,
                    expires_at=foreign.get("expires_at"),
                    lease_id=str(foreign.get("lease_id") or "") or None,
                )
            )
            waiting.append(code)
            continue

        rejected = rejected_by_code.get(code) or []
        if rejected:
            kinds = []
            for item in rejected:
                kinds.extend(item.rejection_kinds)
            kind_text = ",".join(dict.fromkeys(kinds)) or REJECTION_STALE
            action = ACTION_REPAIR
            reason = (
                "prior evidence rejected "
                f"({kind_text}); scheduled exactly once for official reacquisition"
            )
            repair.append(code)
        else:
            action = ACTION_SCHEDULE
            reason = (
                "no verified prior receipt; scheduled exactly once for a leased "
                "live official scrape"
            )
        registry.acquire(
            _build_lease(
                code=code,
                holder=OUL_HOLDER,
                holder_board=OUL_HOLDER_BOARD,
                action=action,
                status=STATUS_SCHEDULED,
                reason=reason,
                prior_receipt_accepted=False,
                byte_verified=False,
                frontier_verified=False,
            )
        )
        scheduled.append(code)

    ordered_scheduled, duplicate_schedules = unique_schedule(scheduled)
    if len(ordered_scheduled) != len(scheduled):
        raise DuplicateScheduleError(
            "internal scheduler emitted a jurisdiction more than once"
        )
    if set(reused) & set(ordered_scheduled) or set(waiting) & set(ordered_scheduled):
        raise DuplicateLeaseError(
            "a reused or waited jurisdiction was also scheduled"
        )
    if len(reused) + len(waiting) + len(ordered_scheduled) != EXPECTED_JURISDICTION_COUNT:
        raise AcquisitionCoordinationError(
            "coordination plan does not cover the exact-51 set exactly once"
        )
    return CoordinationPlan(
        leases=registry.as_tuple(),
        admissions=tuple(admissions),
        scheduled_codes=ordered_scheduled,
        reused_codes=tuple(reused),
        waiting_codes=tuple(waiting),
        repair_codes=tuple(repair),
        duplicate_lease_attempts=registry.duplicate_attempts,
        duplicate_schedule_attempts=duplicate_schedules,
    )


def coordinate_default_prior_evidence(
    *,
    repo_root: Optional[PathLike] = None,
    live_foreign_leases: Optional[Sequence[Mapping[str, Any]]] = None,
    extra_receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    request_bytes: Optional[Mapping[str, bytes]] = None,
    response_bytes: Optional[Mapping[str, bytes]] = None,
    body_bytes: Optional[Mapping[str, bytes]] = None,
) -> CoordinationPlan:
    """Coordinate using discovered state-laws reports plus optional extras."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    receipts: dict[str, Mapping[str, Any]] = {}
    sources: dict[str, tuple[str, str]] = {}
    for receipt, label in discover_state_laws_cohort_receipts(root):
        code = str(receipt.get("jurisdiction") or "").strip().upper()
        if code not in CANONICAL_JURISDICTIONS:
            continue
        receipts[code] = receipt
        sources[code] = (EvidenceSourceKind.STATE_LAWS_COHORT_REPORT.value, label)
    for code, receipt in (extra_receipts or {}).items():
        normalized = str(code).strip().upper()
        receipts[normalized] = receipt
        sources[normalized] = (EvidenceSourceKind.CALLER.value, "caller")
    ledger: dict[str, Mapping[str, Any]] = {}
    for claim, _label in discover_completion_ledger_claims(root):
        code = str(claim.get("jurisdiction") or "").strip().upper()
        if code in CANONICAL_JURISDICTIONS:
            ledger[code] = claim
    return coordinate_jurisdictions(
        receipts=receipts,
        ledger_claims=ledger,
        live_foreign_leases=live_foreign_leases,
        receipt_sources=sources,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        body_bytes=body_bytes,
        admission_index=load_source_admission_index(root / DEFAULT_SOURCE_ADMISSION_RELATIVE_PATH),
    )


# ---------------------------------------------------------------------------
# Report build / validate
# ---------------------------------------------------------------------------


def _rejection_records(plan: CoordinationPlan) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for admission in plan.admissions:
        if admission.accepted:
            continue
        if admission.jurisdiction_code not in CANONICAL_JURISDICTIONS:
            continue
        records.append(
            {
                "detail": admission.detail,
                "jurisdiction_code": admission.jurisdiction_code,
                "rejection_kinds": list(admission.rejection_kinds),
                "row_count": admission.row_count,
                "source_kind": admission.source_kind,
                "source_label": admission.source_label,
            }
        )
    records.sort(
        key=lambda item: (
            item["jurisdiction_code"],
            item["source_kind"],
            item["source_label"],
        )
    )
    return records


def _accepted_records(plan: CoordinationPlan) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for admission in plan.admissions:
        if not admission.accepted:
            continue
        records.append(
            {
                "byte_verified": bool(
                    admission.byte_verification and admission.byte_verification.ok
                ),
                "frontier_verified": bool(
                    admission.frontier_verification and admission.frontier_verification.ok
                ),
                "jurisdiction_code": admission.jurisdiction_code,
                "row_count": admission.row_count,
                "source_kind": admission.source_kind,
                "source_label": admission.source_label,
            }
        )
    records.sort(key=lambda item: item["jurisdiction_code"])
    return records


def _scheduled_records(plan: CoordinationPlan) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lease in plan.leases:
        if lease.action not in {ACTION_SCHEDULE, ACTION_REPAIR}:
            continue
        if lease.jurisdiction_code in seen:
            raise DuplicateScheduleError(
                f"{lease.jurisdiction_code} appears more than once in scheduled scrapes"
            )
        seen.add(lease.jurisdiction_code)
        records.append(
            {
                "action": lease.action,
                "cohort": lease.cohort,
                "jurisdiction_code": lease.jurisdiction_code,
                "lease_id": lease.lease_id,
                "oul_task_id": lease.oul_task_id,
                "reason": lease.reason,
            }
        )
    return records


def build_acquisition_leases_payload(
    plan: Optional[CoordinationPlan] = None,
    *,
    repo_root: Optional[PathLike] = None,
    live_foreign_leases: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build the sealed acquisition-lease report for all 51 jurisdictions."""

    resolved = plan or coordinate_default_prior_evidence(
        repo_root=repo_root,
        live_foreign_leases=live_foreign_leases,
    )
    two_row_rejected = sum(
        1
        for item in resolved.admissions
        if REJECTION_SYNTHETIC_TWO_ROW in item.rejection_kinds
    )
    payload: dict[str, Any] = {
        "accepted_receipts": _accepted_records(resolved),
        "authorizing_for_publication": False,
        "checks": {
            "byte_and_frontier_required_for_reuse": True,
            "completion_ledgers_not_authoritative": True,
            "live_leases_prevent_duplicate_scrapes": True,
            "missing_or_invalid_scheduled_exactly_once": True,
            "synthetic_two_row_rejected": True,
        },
        "code_version": CODE_VERSION,
        "description": (
            "Exclusive exact-51 acquisition leases. Prior state-laws supervisor "
            "receipts are reused only after byte and frontier verification. "
            "Synthetic two-row reports and completion ledgers are rejected. "
            "Live foreign leases are waited on. Missing or invalid jurisdictions "
            "are scheduled exactly once."
        ),
        "duplicate_lease_attempts": resolved.duplicate_lease_attempts,
        "duplicate_schedule_attempts": resolved.duplicate_schedule_attempts,
        "goal_id": GOAL_ID,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "leases": [item.to_dict() for item in resolved.leases],
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "rejected_prior_evidence": _rejection_records(resolved),
        "report_schema": REPORT_SCHEMA,
        "required_jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "reused_jurisdiction_codes": list(resolved.reused_codes),
        "scheduled_jurisdiction_codes": list(resolved.scheduled_codes),
        "scheduled_scrapes": _scheduled_records(resolved),
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "summary": resolved.to_summary(),
        "task_id": TASK_ID,
        "two_row_reports_rejected": two_row_rejected,
        "waiting_jurisdiction_codes": list(resolved.waiting_codes),
    }
    if len(payload["leases"]) != EXPECTED_JURISDICTION_COUNT:
        raise LeaseReportError("lease report must contain exactly 51 leases")
    assert_no_secrets(payload)
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


def validate_acquisition_leases(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a sealed acquisition-lease report. Fail closed."""

    if not isinstance(payload, Mapping):
        raise LeaseReportError("acquisition lease report root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LeaseReportError("schema_version must be open-us-law-acquisition-leases-v1")
    if payload.get("task_id") != TASK_ID:
        raise LeaseReportError(f"task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise LeaseReportError(f"goal_id must be {GOAL_ID}")
    if payload.get("program_id") != PROGRAM_ID:
        raise LeaseReportError(f"program_id must be {PROGRAM_ID}")
    if payload.get("producer") != PRODUCER:
        raise LeaseReportError(f"producer must be {PRODUCER}")
    if payload.get("authorizing_for_publication") is not False:
        raise LeaseReportError("lease report cannot authorize publication")
    if payload.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT:
        raise LeaseReportError("jurisdiction_count must be 51")
    required = payload.get("required_jurisdiction_codes")
    if required != list(CANONICAL_JURISDICTION_ORDER):
        raise LeaseReportError("required_jurisdiction_codes must be the exact-51 order")

    leases = payload.get("leases")
    if not isinstance(leases, list) or len(leases) != EXPECTED_JURISDICTION_COUNT:
        raise LeaseReportError("leases must contain exactly 51 objects")
    observed: list[str] = []
    lease_by_code: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(leases):
        if not isinstance(row, Mapping):
            raise LeaseReportError(f"leases[{index}] must be an object")
        code = str(row.get("jurisdiction_code") or "").strip().upper()
        if code not in CANONICAL_JURISDICTIONS:
            raise LeaseReportError(f"leases[{index}] has invalid jurisdiction {code}")
        if code in lease_by_code:
            raise DuplicateLeaseError(f"duplicate lease for {code}")
        action = str(row.get("action") or "")
        if action not in {ACTION_REUSE, ACTION_SCHEDULE, ACTION_REPAIR, ACTION_WAIT}:
            raise LeaseReportError(f"{code} has unknown lease action {action}")
        if action == ACTION_REUSE:
            if row.get("prior_receipt_accepted") is not True:
                raise LeaseReportError(f"{code} reuse requires an accepted prior receipt")
            if row.get("byte_verified") is not True or row.get("frontier_verified") is not True:
                raise LeaseReportError(
                    f"{code} reuse requires byte and frontier verification"
                )
        if action == ACTION_WAIT:
            if str(row.get("holder") or "") == OUL_HOLDER:
                raise LeaseReportError(
                    f"{code} wait_live_lease must be held by the foreign scraper"
                )
        if row.get("prevents_duplicate_scrape") is not True:
            raise LeaseReportError(f"{code} lease must prevent duplicate scraping")
        observed.append(code)
        lease_by_code[code] = row
    if observed != list(CANONICAL_JURISDICTION_ORDER):
        raise LeaseReportError("leases must follow canonical exact-51 order")
    if observed.count("DC") != 1:
        raise LeaseReportError("DC must appear exactly once")
    extra = [code for code in observed if code in FORBIDDEN_DEFAULT_JURISDICTIONS]
    if extra:
        raise LeaseReportError("default leases include forbidden jurisdictions")

    scheduled = payload.get("scheduled_jurisdiction_codes")
    if not isinstance(scheduled, list):
        raise LeaseReportError("scheduled_jurisdiction_codes must be a list")
    scheduled_codes = [str(item).strip().upper() for item in scheduled]
    unique_codes, duplicates = unique_schedule(scheduled_codes)
    if duplicates or list(unique_codes) != scheduled_codes:
        raise DuplicateScheduleError(
            "scheduled_jurisdiction_codes must list each jurisdiction exactly once"
        )
    scrapes = payload.get("scheduled_scrapes")
    if not isinstance(scrapes, list):
        raise LeaseReportError("scheduled_scrapes must be a list")
    scrape_codes = [
        str(item.get("jurisdiction_code") or "").strip().upper()
        for item in scrapes
        if isinstance(item, Mapping)
    ]
    if scrape_codes != scheduled_codes:
        raise LeaseReportError(
            "scheduled_scrapes must match scheduled_jurisdiction_codes exactly once"
        )

    reused = [
        str(item).strip().upper()
        for item in (payload.get("reused_jurisdiction_codes") or [])
    ]
    waiting = [
        str(item).strip().upper()
        for item in (payload.get("waiting_jurisdiction_codes") or [])
    ]
    if set(reused) & set(scheduled_codes):
        raise DuplicateLeaseError("a reused jurisdiction was also scheduled")
    if set(waiting) & set(scheduled_codes):
        raise DuplicateLeaseError("a waited live lease was also scheduled")
    covered = set(reused) | set(waiting) | set(scheduled_codes)
    if covered != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - covered)
        extra_codes = sorted(covered - CANONICAL_JURISDICTIONS)
        raise LeaseReportError(
            f"lease coverage is not exact-51; missing={missing} extra={extra_codes}"
        )

    for row in payload.get("accepted_receipts") or []:
        if not isinstance(row, Mapping):
            raise LeaseReportError("accepted_receipts entries must be objects")
        if row.get("byte_verified") is not True or row.get("frontier_verified") is not True:
            raise LeaseReportError(
                "accepted receipts require byte and frontier verification"
            )
        if _as_int(row.get("row_count")) == TWO_ROW_COUNT:
            raise LeaseReportError("synthetic two-row reports cannot be accepted")
        if _as_int(row.get("row_count")) == 0:
            raise LeaseReportError("zero-row success cannot be accepted")
        if row.get("raw_bytes_checked") is False:
            raise LeaseReportError("accepted receipts cannot set raw_bytes_checked=false")

    for row in payload.get("rejected_prior_evidence") or []:
        if not isinstance(row, Mapping):
            continue
        kinds = row.get("rejection_kinds") or []
        if REJECTION_SYNTHETIC_TWO_ROW in kinds and row.get("jurisdiction_code") in reused:
            raise LeaseReportError("a rejected two-row report was also reused")

    checks = payload.get("checks")
    if not isinstance(checks, Mapping) or checks.get("synthetic_two_row_rejected") is not True:
        raise LeaseReportError("checks.synthetic_two_row_rejected must be true")
    if checks.get("byte_and_frontier_required_for_reuse") is not True:
        raise LeaseReportError("checks.byte_and_frontier_required_for_reuse must be true")
    if checks.get("live_leases_prevent_duplicate_scrapes") is not True:
        raise LeaseReportError("checks.live_leases_prevent_duplicate_scrapes must be true")
    if checks.get("missing_or_invalid_scheduled_exactly_once") is not True:
        raise LeaseReportError(
            "checks.missing_or_invalid_scheduled_exactly_once must be true"
        )

    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    digest = str(payload.get("report_digest_sha256") or "")
    if not _SHA256_RE.fullmatch(digest):
        raise LeaseReportError("report_digest_sha256 is not a SHA-256 digest")
    expected = sha256_json(body)
    if digest != expected:
        raise LeaseReportError("report_digest_sha256 does not match canonical report bytes")
    assert_no_secrets(payload)
    return {
        "dc_counted_once": observed.count("DC") == 1,
        "exact_51": observed == list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": len(observed),
        "jurisdiction_codes": observed,
        "reused": reused,
        "scheduled": scheduled_codes,
        "status": "passed",
        "waiting": waiting,
        "report_digest_sha256": digest,
    }


def require_live_verified_receipts(
    payload: Mapping[str, Any],
    *,
    cohort: Optional[str] = None,
) -> None:
    """Fail closed when --require-live is set and verified receipts are missing."""

    codes = list(cohort_codes(cohort)) if cohort else list(CANONICAL_JURISDICTION_ORDER)
    lease_by_code = {
        str(row.get("jurisdiction_code")): row
        for row in (payload.get("leases") or [])
        if isinstance(row, Mapping)
    }
    missing: list[str] = []
    for code in codes:
        row = lease_by_code.get(code)
        if not isinstance(row, Mapping):
            missing.append(code)
            continue
        if (
            row.get("action") == ACTION_REUSE
            and row.get("prior_receipt_accepted") is True
            and row.get("byte_verified") is True
            and row.get("frontier_verified") is True
        ):
            continue
        missing.append(code)
    if missing:
        scope = f"cohort {cohort}" if cohort else "exact-51"
        raise LiveEvidenceRequiredError(
            f"--require-live has no verified live receipts for {scope}: "
            + ",".join(missing)
        )


def check_declared_cohort_report(
    path: PathLike,
    *,
    cohort: Optional[str] = None,
    require_live: bool = False,
    repo_root: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Validate the declared Open US Law cohort report (not legal_corpora)."""

    from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
        check_declared_cohort_report as _check_cohort,
    )

    return _check_cohort(
        path,
        cohort=cohort,
        require_live=require_live,
        repo_root=repo_root,
    )


def check_committed_leases(
    *,
    repo_root: Optional[PathLike] = None,
    require_live: bool = False,
    cohort: Optional[str] = None,
    report_path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Rebuild the sealed report and require the committed bytes to match.

    When ``report_path`` points at a declared Open US Law cohort evidence
    report, cohort-scoped checks consume that file instead of the older
    ``legal_corpora_reindex`` receipt directory.
    """

    root = Path(repo_root) if repo_root is not None else repository_root()
    if report_path is not None:
        declared = Path(report_path)
        if declared.is_file():
            try:
                payload = json.loads(declared.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LeaseReportError(
                    f"declared report is not valid JSON: {declared}"
                ) from exc
            if is_cohort_evidence_payload(payload):
                return check_declared_cohort_report(
                    declared,
                    cohort=cohort,
                    require_live=require_live,
                    repo_root=root,
                )
        elif require_live or (
            cohort and "cohort_" in declared.name.lower()
        ):
            scope = f"cohort {cohort}" if cohort else "declared cohort report"
            raise LiveEvidenceRequiredError(
                f"--require-live has no declared cohort report for {scope}: {declared}"
            )
    path = default_lease_report_path(root)
    if not path.is_file():
        raise LeaseReportError(f"committed acquisition lease report missing: {path}")
    committed_bytes = path.read_bytes()
    generated = build_acquisition_leases_payload(repo_root=root)
    generated_bytes = encode_acquisition_leases(generated)
    if committed_bytes != generated_bytes:
        raise LeaseReportError(
            "committed acquisition_leases.json differs from the deterministic "
            "coordinator builder; regenerate and commit the sealed report"
        )
    committed = json.loads(committed_bytes.decode("utf-8"))
    projection = validate_acquisition_leases(committed)
    if require_live:
        require_live_verified_receipts(committed, cohort=cohort)
    elif cohort:
        expected = set(cohort_codes(cohort))
        lease_codes = {
            str(row.get("jurisdiction_code"))
            for row in committed.get("leases") or []
            if isinstance(row, Mapping)
        }
        if not expected <= lease_codes:
            raise LeaseReportError(
                f"cohort {cohort} jurisdictions missing from committed leases"
            )
    report = {
        "authorizing_for_publication": False,
        "checks": committed.get("checks"),
        "code_version": CODE_VERSION,
        "cohort": str(cohort).strip().upper() if cohort else None,
        "duplicate_lease_attempts": committed.get("duplicate_lease_attempts", 0),
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "report_schema": REPORT_SCHEMA,
        "require_live": require_live,
        "scheduled_count": len(committed.get("scheduled_jurisdiction_codes") or []),
        "task_id": TASK_ID,
        "two_row_reports_rejected": committed.get("two_row_reports_rejected", 0),
        **projection,
    }
    return report


def write_acquisition_leases(
    path: PathLike,
    payload: Optional[Mapping[str, Any]] = None,
    *,
    repo_root: Optional[PathLike] = None,
) -> Path:
    """Atomically write the sealed acquisition-lease report."""

    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    document = (
        dict(payload)
        if payload is not None
        else build_acquisition_leases_payload(repo_root=repo_root)
    )
    validate_acquisition_leases(document)
    encoded = encode_acquisition_leases(document)
    tmp = report_path.with_name(report_path.name + ".tmp")
    tmp.write_bytes(encoded)
    tmp.replace(report_path)
    return report_path


__all__ = [
    "ACTION_REPAIR",
    "ACTION_REUSE",
    "ACTION_SCHEDULE",
    "ACTION_WAIT",
    "AcquisitionCoordinationError",
    "ByteVerification",
    "COHORT_EVIDENCE_SCHEMA_VERSION",
    "COHORT_JURISDICTIONS",
    "CoordinationPlan",
    "DuplicateLeaseError",
    "DuplicateScheduleError",
    "EXPECTED_JURISDICTION_COUNT",
    "FrontierVerification",
    "GOAL_ID",
    "JurisdictionLease",
    "LeaseRegistry",
    "LeaseReportError",
    "LiveEvidenceRequiredError",
    "OUL_HOLDER",
    "PROGRAM_ID",
    "PRODUCER",
    "ReceiptAdmission",
    "SCHEMA_VERSION",
    "SEALED_AT",
    "STATE_LAWS_HOLDER",
    "TASK_ID",
    "build_acquisition_leases_payload",
    "check_committed_leases",
    "check_declared_cohort_report",
    "cohort_codes",
    "cohort_letter",
    "cohort_task_id",
    "coordinate_default_prior_evidence",
    "coordinate_jurisdictions",
    "default_cohort_report_path",
    "default_lease_report_path",
    "is_cohort_evidence_payload",
    "is_placeholder_cid",
    "is_placeholder_digest",
    "discover_completion_ledger_claims",
    "discover_live_foreign_leases",
    "discover_state_laws_cohort_receipts",
    "encode_acquisition_leases",
    "evaluate_prior_receipt",
    "is_completion_ledger_claim",
    "is_synthetic_two_row_report",
    "lease_id_for",
    "require_live_verified_receipts",
    "require_scheduled_exactly_once",
    "unique_schedule",
    "validate_acquisition_leases",
    "verify_receipt_bytes",
    "verify_receipt_frontier",
    "write_acquisition_leases",
]
