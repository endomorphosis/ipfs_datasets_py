"""Deterministic privacy, rights, and classification gates for JusticeDAO patent releases.

Public JusticeDAO publication is fail-closed:

* only ``public_official`` / ``public_user`` classifications are admitted;
* any private, unknown, or mixed batch is rejected **before** staging;
* every candidate must carry reviewed rights evidence and source lineage;
* secret-bearing text blocks admission (matched values are never retained).

This module never uploads, authenticates, or contacts Hugging Face.  It only
produces bounded admission decisions and projected public rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Final, Pattern


RELEASE_POLICY_VERSION: Final = "patent-legal-release-policy/v1"
MAX_SCAN_FIELD_CHARS: Final = 1_048_576
MAX_FINDINGS: Final = 256
MAX_RECORDS_PER_BATCH: Final = 250_000

# Configurable public shard families for official law + public patent/index data.
ARTIFACT_KINDS: Final[tuple[str, ...]] = (
    "cfr",
    "usc",
    "public_law",
    "federal_register",
    "projected_rules",
    "applications",
    "claims",
    "events",
    "office_actions",
    "citations",
    "graph",
    "bm25",
    "vector_metadata",
)
ARTIFACT_KIND_SET: Final[frozenset[str]] = frozenset(ARTIFACT_KINDS)

PUBLIC_CLASSIFICATIONS: Final[frozenset[str]] = frozenset(
    {"public_official", "public_user"}
)
PRIVATE_CLASSIFICATIONS: Final[frozenset[str]] = frozenset(
    {
        "confidential_application",
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
    }
)
ALL_CLASSIFICATIONS: Final[frozenset[str]] = (
    PUBLIC_CLASSIFICATIONS | PRIVATE_CLASSIFICATIONS | frozenset({"unknown"})
)

_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")


class ReleasePolicyError(ValueError):
    """Raised when release-policy input is malformed or unverifiable."""


class PublicationRejectedError(ReleasePolicyError):
    """Raised when a caller requires an admitted public publication."""


class PrivacyRejectedError(PublicationRejectedError):
    """Raised when private or mixed disclosure material is present."""


class ClassificationStatus(str, Enum):
    PUBLIC_OFFICIAL = "public_official"
    PUBLIC_USER = "public_user"
    CONFIDENTIAL_APPLICATION = "confidential_application"
    PRIVILEGED_WORK_PRODUCT = "privileged_work_product"
    RESTRICTED_EXPORT_REVIEW = "restricted_export_review"
    CREDENTIAL_OR_PAYMENT = "credential_or_payment"
    UNKNOWN = "unknown"


class RightsReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    REJECTED = "rejected"


class FindingCategory(str, Enum):
    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    UNSAFE_PATH = "unsafe_path"
    SCAN_LIMIT = "scan_limit"
    CLASSIFICATION = "classification"
    RIGHTS = "rights"
    LINEAGE = "lineage"


class ArtifactKind(str, Enum):
    CFR = "cfr"
    USC = "usc"
    PUBLIC_LAW = "public_law"
    FEDERAL_REGISTER = "federal_register"
    PROJECTED_RULES = "projected_rules"
    APPLICATIONS = "applications"
    CLAIMS = "claims"
    EVENTS = "events"
    OFFICE_ACTIONS = "office_actions"
    CITATIONS = "citations"
    GRAPH = "graph"
    BM25 = "bm25"
    VECTOR_METADATA = "vector_metadata"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReleasePolicyError(f"{label} must be a lowercase 64-char hex SHA-256")
    return value


def _require_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ReleasePolicyError(
            f"{label} must be non-empty trimmed text without NUL (max {maximum})"
        )
    return value


def _coerce_classification(value: Any) -> ClassificationStatus:
    if isinstance(value, ClassificationStatus):
        return value
    if isinstance(value, str):
        try:
            return ClassificationStatus(value.strip())
        except ValueError as exc:
            raise ReleasePolicyError(
                f"unknown disclosure classification: {value!r}"
            ) from exc
    raise ReleasePolicyError(
        f"classification must be str or ClassificationStatus, got {type(value).__name__}"
    )


def _coerce_artifact_kind(value: Any) -> ArtifactKind:
    if isinstance(value, ArtifactKind):
        return value
    if isinstance(value, str):
        try:
            return ArtifactKind(value.strip())
        except ValueError as exc:
            raise ReleasePolicyError(
                f"unsupported artifact_kind: {value!r}; "
                f"expected one of {', '.join(ARTIFACT_KINDS)}"
            ) from exc
    raise ReleasePolicyError(
        f"artifact_kind must be str or ArtifactKind, got {type(value).__name__}"
    )


def is_public_classification(value: ClassificationStatus | str) -> bool:
    return _coerce_classification(value).value in PUBLIC_CLASSIFICATIONS


def is_private_classification(value: ClassificationStatus | str) -> bool:
    return _coerce_classification(value).value in PRIVATE_CLASSIFICATIONS


def requires_quarantine(value: ClassificationStatus | str) -> bool:
    return _coerce_classification(value) is ClassificationStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class SourceLineage:
    """Immutable source authority binding for one release candidate row."""

    source_id: str
    source_revision: str
    source_uri: str
    source_sha256: str
    authority: str = "official"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _require_text(self.source_id, "source_id", maximum=256)
        )
        object.__setattr__(
            self,
            "source_revision",
            _require_text(self.source_revision, "source_revision", maximum=256),
        )
        uri = _require_text(self.source_uri, "source_uri", maximum=2048)
        if not (
            uri.startswith("https://")
            or uri.startswith("hf://")
            or uri.startswith("ipfs://")
            or uri.startswith("govinfo://")
            or uri.startswith("uspto://")
        ):
            raise ReleasePolicyError(
                "source_uri must use https://, hf://, ipfs://, govinfo://, or uspto://"
            )
        object.__setattr__(self, "source_uri", uri)
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256")
        )
        object.__setattr__(
            self,
            "authority",
            _require_text(self.authority, "authority", maximum=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_sha256": self.source_sha256,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceLineage":
        if not isinstance(value, Mapping):
            raise ReleasePolicyError("source_lineage must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            source_revision=value.get("source_revision", ""),
            source_uri=value.get("source_uri", ""),
            source_sha256=value.get("source_sha256", ""),
            authority=value.get("authority", "official"),
        )


@dataclass(frozen=True, slots=True)
class RightsReview:
    """Human rights/redistribution review bound to public release candidates."""

    license_expression: str
    review_status: RightsReviewStatus
    reviewed_by: str
    reviewed_at: str
    redistribution_allowed: bool
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "license_expression",
            _require_text(self.license_expression, "license_expression", maximum=256),
        )
        if not isinstance(self.review_status, RightsReviewStatus):
            try:
                object.__setattr__(
                    self,
                    "review_status",
                    RightsReviewStatus(str(self.review_status)),
                )
            except ValueError as exc:
                raise ReleasePolicyError("rights review_status is invalid") from exc
        if type(self.redistribution_allowed) is not bool:
            raise ReleasePolicyError("redistribution_allowed must be boolean")
        if self.review_status is RightsReviewStatus.REVIEWED:
            object.__setattr__(
                self,
                "reviewed_by",
                _require_text(self.reviewed_by, "reviewed_by", maximum=256),
            )
            if not _RFC3339_UTC_RE.fullmatch(self.reviewed_at):
                raise ReleasePolicyError(
                    "reviewed rights require RFC3339 UTC reviewed_at"
                )
        else:
            if self.reviewed_by or self.reviewed_at:
                raise ReleasePolicyError(
                    "unreviewed/rejected rights cannot claim review metadata"
                )
            object.__setattr__(self, "reviewed_by", "")
            object.__setattr__(self, "reviewed_at", "")
        if self.notes is None:
            object.__setattr__(self, "notes", "")
        elif not isinstance(self.notes, str) or "\x00" in self.notes:
            raise ReleasePolicyError("rights notes must be a string without NUL")
        elif len(self.notes) > 2048:
            raise ReleasePolicyError("rights notes exceed 2048 characters")

    @property
    def reviewed_for_release(self) -> bool:
        return (
            self.review_status is RightsReviewStatus.REVIEWED
            and self.redistribution_allowed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_expression": self.license_expression,
            "notes": self.notes,
            "redistribution_allowed": self.redistribution_allowed,
            "review_status": self.review_status.value,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RightsReview":
        if not isinstance(value, Mapping):
            raise ReleasePolicyError("rights_review must be a mapping")
        status_raw = value.get("review_status", RightsReviewStatus.UNREVIEWED.value)
        try:
            status = (
                status_raw
                if isinstance(status_raw, RightsReviewStatus)
                else RightsReviewStatus(str(status_raw))
            )
        except ValueError as exc:
            raise ReleasePolicyError("rights review_status is invalid") from exc
        return cls(
            license_expression=value.get("license_expression", ""),
            review_status=status,
            reviewed_by=value.get("reviewed_by", ""),
            reviewed_at=value.get("reviewed_at", ""),
            redistribution_allowed=bool(value.get("redistribution_allowed", False)),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """Bounded location and code; matched sensitive text is never retained."""

    category: FindingCategory
    code: str
    field: str
    start_char: int
    end_char: int
    value_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, FindingCategory):
            raise ReleasePolicyError("finding category is invalid")
        object.__setattr__(self, "code", _require_text(self.code, "finding code", maximum=128))
        object.__setattr__(self, "field", _require_text(self.field, "finding field", maximum=256))
        if (
            type(self.start_char) is not int
            or type(self.end_char) is not int
            or self.start_char < 0
            or self.end_char < self.start_char
        ):
            raise ReleasePolicyError("finding offsets are invalid")
        object.__setattr__(
            self, "value_sha256", _require_sha256(self.value_sha256, "finding value_sha256")
        )

    @property
    def blocks_release(self) -> bool:
        return self.category in {
            FindingCategory.SECRET,
            FindingCategory.UNSAFE_PATH,
            FindingCategory.SCAN_LIMIT,
            FindingCategory.CLASSIFICATION,
            FindingCategory.RIGHTS,
            FindingCategory.LINEAGE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "code": self.code,
            "end_char": self.end_char,
            "field": self.field,
            "start_char": self.start_char,
            "value_sha256": self.value_sha256,
        }


@dataclass(frozen=True, slots=True)
class _Detector:
    category: FindingCategory
    code: str
    pattern: Pattern[str]


def _pattern(value: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Pattern[str]:
    return re.compile(value, flags)


_DETECTORS: Final = (
    _Detector(
        FindingCategory.SECRET,
        "secret.private_key",
        _pattern(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.aws_access_key",
        _pattern(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])", 0),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.github_token",
        _pattern(
            r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
            r"github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9])"
        ),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.hf_token",
        _pattern(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{20,255}(?![A-Za-z0-9])"),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.api_token",
        _pattern(
            r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
            r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
        ),
    ),
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.email",
        _pattern(
            r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
            r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
            r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+"
            r"(?![A-Za-z0-9-])"
        ),
    ),
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.us_ssn",
        _pattern(
            r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ]"
            r"(?!00)\d{2}[- ](?!0000)\d{4}(?!\d)"
        ),
    ),
)

_POLICY_MANIFEST = {
    "artifact_kinds": list(ARTIFACT_KINDS),
    "detectors": [
        {
            "category": detector.category.value,
            "code": detector.code,
            "flags": detector.pattern.flags,
            "pattern": detector.pattern.pattern,
        }
        for detector in _DETECTORS
    ],
    "max_findings": MAX_FINDINGS,
    "max_records_per_batch": MAX_RECORDS_PER_BATCH,
    "max_scan_field_chars": MAX_SCAN_FIELD_CHARS,
    "private_classifications": sorted(PRIVATE_CLASSIFICATIONS),
    "public_classifications": sorted(PUBLIC_CLASSIFICATIONS),
    "version": RELEASE_POLICY_VERSION,
}
RELEASE_POLICY_SHA256: Final = hashlib.sha256(
    json.dumps(
        _POLICY_MANIFEST,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """One public-release candidate row with lineage, classification, and rights."""

    record_id: str
    artifact_kind: ArtifactKind
    classification: ClassificationStatus
    payload: Mapping[str, Any]
    source_lineage: SourceLineage
    rights_review: RightsReview

    def __post_init__(self) -> None:
        rid = _require_text(self.record_id, "record_id", maximum=256)
        if not _RECORD_ID_RE.fullmatch(rid):
            raise ReleasePolicyError("record_id has invalid characters")
        object.__setattr__(self, "record_id", rid)
        object.__setattr__(self, "artifact_kind", _coerce_artifact_kind(self.artifact_kind))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.source_lineage, SourceLineage):
            raise ReleasePolicyError("source_lineage must be SourceLineage")
        if not isinstance(self.rights_review, RightsReview):
            raise ReleasePolicyError("rights_review must be RightsReview")
        if not isinstance(self.payload, Mapping):
            raise ReleasePolicyError("payload must be a mapping")
        try:
            normalized = json.loads(_canonical_json(dict(self.payload)))
        except (TypeError, ValueError, RecursionError) as exc:
            raise ReleasePolicyError(
                "payload must contain finite JSON-compatible values"
            ) from exc
        if not isinstance(normalized, dict):
            raise ReleasePolicyError("payload must encode as an object")
        object.__setattr__(self, "payload", MappingProxyType(normalized))

    @property
    def record_sha256(self) -> str:
        return _sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.artifact_kind.value,
            "classification": self.classification.value,
            "payload": dict(self.payload),
            "record_id": self.record_id,
            "rights_review": self.rights_review.to_dict(),
            "source_lineage": self.source_lineage.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseCandidate":
        if not isinstance(value, Mapping):
            raise ReleasePolicyError("release candidate must be a mapping")
        rights = value.get("rights_review")
        lineage = value.get("source_lineage")
        return cls(
            record_id=str(value.get("record_id") or ""),
            artifact_kind=value.get("artifact_kind", ""),
            classification=value.get("classification", ClassificationStatus.UNKNOWN.value),
            payload=value.get("payload") if isinstance(value.get("payload"), Mapping) else {},
            source_lineage=(
                lineage
                if isinstance(lineage, SourceLineage)
                else SourceLineage.from_dict(lineage if isinstance(lineage, Mapping) else {})
            ),
            rights_review=(
                rights
                if isinstance(rights, RightsReview)
                else RightsReview.from_dict(rights if isinstance(rights, Mapping) else {})
            ),
        )


@dataclass(frozen=True, slots=True)
class RecordAdmission:
    """Admission decision for one candidate row."""

    admitted: bool
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    findings: tuple[PolicyFinding, ...]
    candidate: ReleaseCandidate
    projected_record: Mapping[str, Any]
    policy_sha256: str
    policy_version: str = RELEASE_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.admitted != (not self.reason_codes):
            raise ReleasePolicyError(
                "admitted must be false exactly when reason_codes are present"
            )
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ReleasePolicyError("reason_codes must be sorted and unique")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ReleasePolicyError("warning_codes must be sorted and unique")
        object.__setattr__(
            self,
            "projected_record",
            MappingProxyType(dict(self.projected_record)),
        )
        _require_sha256(self.policy_sha256, "admission policy_sha256")

    def require_admitted(self) -> "RecordAdmission":
        if not self.admitted:
            raise PublicationRejectedError(
                "publication rejected: " + ", ".join(self.reason_codes)
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "findings": [item.to_dict() for item in self.findings],
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "projected_record": dict(self.projected_record),
            "reason_codes": list(self.reason_codes),
            "record_id": self.candidate.record_id,
            "warning_codes": list(self.warning_codes),
        }


@dataclass(frozen=True, slots=True)
class BatchAdmission:
    """Fail-closed decision for an entire release batch (no partial staging)."""

    admitted: bool
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    record_admissions: tuple[RecordAdmission, ...]
    classification_summary: Mapping[str, int]
    policy_sha256: str
    policy_version: str = RELEASE_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.admitted != (not self.reason_codes):
            raise ReleasePolicyError(
                "batch admitted must be false exactly when reason_codes are present"
            )
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ReleasePolicyError("batch reason_codes must be sorted and unique")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ReleasePolicyError("batch warning_codes must be sorted and unique")
        object.__setattr__(
            self,
            "classification_summary",
            MappingProxyType(dict(self.classification_summary)),
        )
        _require_sha256(self.policy_sha256, "batch policy_sha256")

    @property
    def admitted_records(self) -> tuple[ReleaseCandidate, ...]:
        if not self.admitted:
            return ()
        return tuple(item.candidate for item in self.record_admissions if item.admitted)

    @property
    def projected_records(self) -> tuple[Mapping[str, Any], ...]:
        if not self.admitted:
            return ()
        return tuple(
            item.projected_record for item in self.record_admissions if item.admitted
        )

    def require_admitted(self) -> "BatchAdmission":
        if not self.admitted:
            raise PrivacyRejectedError(
                "batch rejected before staging: " + ", ".join(self.reason_codes)
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "classification_summary": dict(self.classification_summary),
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
            "record_admissions": [item.to_dict() for item in self.record_admissions],
            "record_count": len(self.record_admissions),
            "warning_codes": list(self.warning_codes),
        }


class PatentReleasePolicy:
    """Side-effect-free privacy/rights/classification gate for patent releases."""

    def __init__(self, *, max_field_chars: int = MAX_SCAN_FIELD_CHARS) -> None:
        if (
            type(max_field_chars) is not int
            or max_field_chars <= 0
            or max_field_chars > MAX_SCAN_FIELD_CHARS
        ):
            raise ReleasePolicyError(
                f"max_field_chars must be between 1 and {MAX_SCAN_FIELD_CHARS}"
            )
        self.max_field_chars = max_field_chars

    @property
    def policy_sha256(self) -> str:
        return RELEASE_POLICY_SHA256

    def scan_payload(
        self, payload: Mapping[str, Any], *, field_prefix: str = "payload"
    ) -> tuple[PolicyFinding, ...]:
        findings: list[PolicyFinding] = []
        for field, value in _iter_text_fields(payload, prefix=field_prefix):
            findings.extend(self._scan_text(field, value))
            if len(findings) >= MAX_FINDINGS:
                findings = findings[:MAX_FINDINGS]
                findings.append(
                    PolicyFinding(
                        category=FindingCategory.SCAN_LIMIT,
                        code="scan.finding_limit_exceeded",
                        field=field,
                        start_char=0,
                        end_char=min(len(value), self.max_field_chars),
                        value_sha256=_sha256_text(value),
                    )
                )
                break
        ordered = sorted(findings, key=_finding_sort_key)
        dedup: dict[tuple[Any, ...], PolicyFinding] = {}
        for finding in ordered:
            dedup[_finding_sort_key(finding)] = finding
        return tuple(dedup[key] for key in sorted(dedup))

    def evaluate_record(self, candidate: ReleaseCandidate | Mapping[str, Any]) -> RecordAdmission:
        record = (
            candidate
            if isinstance(candidate, ReleaseCandidate)
            else ReleaseCandidate.from_dict(candidate)
        )
        reasons: set[str] = set()
        warnings: set[str] = set()
        findings: list[PolicyFinding] = []

        if requires_quarantine(record.classification):
            reasons.add("classification.unknown_quarantine")
            findings.append(
                PolicyFinding(
                    category=FindingCategory.CLASSIFICATION,
                    code="classification.unknown",
                    field="classification",
                    start_char=0,
                    end_char=len(record.classification.value),
                    value_sha256=_sha256_text(record.classification.value),
                )
            )
        elif is_private_classification(record.classification):
            reasons.add("classification.private")
            findings.append(
                PolicyFinding(
                    category=FindingCategory.CLASSIFICATION,
                    code=f"classification.{record.classification.value}",
                    field="classification",
                    start_char=0,
                    end_char=len(record.classification.value),
                    value_sha256=_sha256_text(record.classification.value),
                )
            )
        elif not is_public_classification(record.classification):
            reasons.add("classification.not_public")

        if not record.rights_review.reviewed_for_release:
            if record.rights_review.review_status is RightsReviewStatus.UNREVIEWED:
                reasons.add("rights.unreviewed")
            elif record.rights_review.review_status is RightsReviewStatus.REJECTED:
                reasons.add("rights.rejected")
            if not record.rights_review.redistribution_allowed:
                reasons.add("rights.redistribution_not_allowed")
            findings.append(
                PolicyFinding(
                    category=FindingCategory.RIGHTS,
                    code="rights.not_reviewed_for_release",
                    field="rights_review",
                    start_char=0,
                    end_char=0,
                    value_sha256=_sha256_json(record.rights_review.to_dict()),
                )
            )

        # Lineage is required by construction; re-check hash binding.
        if not _SHA256_RE.fullmatch(record.source_lineage.source_sha256):
            reasons.add("lineage.invalid_source_sha256")
            findings.append(
                PolicyFinding(
                    category=FindingCategory.LINEAGE,
                    code="lineage.invalid_source_sha256",
                    field="source_lineage.source_sha256",
                    start_char=0,
                    end_char=0,
                    value_sha256=_sha256_text(record.source_lineage.source_sha256 or "missing"),
                )
            )

        payload_findings = self.scan_payload(record.payload)
        findings.extend(payload_findings)
        for finding in payload_findings:
            if finding.category is FindingCategory.SECRET:
                reasons.add("content.secret_detected")
            elif finding.category is FindingCategory.SCAN_LIMIT:
                reasons.add("scan.incomplete")
            elif finding.category is FindingCategory.PERSONAL_DATA:
                # Public official law/patent text may cite contact emails; warn only.
                if record.classification is ClassificationStatus.PUBLIC_OFFICIAL:
                    warnings.add("privacy.personal_data_in_public_official")
                else:
                    reasons.add("privacy.personal_data_unredacted")

        ordered_findings = tuple(
            sorted({_finding_sort_key(f): f for f in findings}.values(), key=_finding_sort_key)
        )
        projected = _project_public_record(record)
        return RecordAdmission(
            admitted=not reasons,
            reason_codes=tuple(sorted(reasons)),
            warning_codes=tuple(sorted(warnings)),
            findings=ordered_findings,
            candidate=record,
            projected_record=projected,
            policy_sha256=self.policy_sha256,
        )

    def evaluate_batch(
        self,
        candidates: Sequence[ReleaseCandidate | Mapping[str, Any]],
        *,
        expected_policy_sha256: str = RELEASE_POLICY_SHA256,
    ) -> BatchAdmission:
        """Admit an entire batch or reject it before staging.

        Private and mixed inputs always fail closed: a single private/unknown
        row rejects the whole batch so staging never receives partial public
        material mixed with non-public disclosure classes.
        """

        if not isinstance(candidates, Sequence) or isinstance(
            candidates, (str, bytes, bytearray)
        ):
            raise ReleasePolicyError("candidates must be a sequence of records")
        if len(candidates) == 0:
            raise ReleasePolicyError("candidates must be non-empty")
        if len(candidates) > MAX_RECORDS_PER_BATCH:
            raise ReleasePolicyError(
                f"candidates exceed max_records_per_batch ({MAX_RECORDS_PER_BATCH})"
            )

        batch_reasons: set[str] = set()
        batch_warnings: set[str] = set()
        if expected_policy_sha256 != self.policy_sha256:
            batch_reasons.add("policy.drift")

        admissions: list[RecordAdmission] = []
        seen_ids: set[str] = set()
        classification_counts: dict[str, int] = {}
        for raw in candidates:
            admission = self.evaluate_record(raw)
            admissions.append(admission)
            rid = admission.candidate.record_id
            if rid in seen_ids:
                batch_reasons.add("batch.duplicate_record_id")
            seen_ids.add(rid)
            cls_value = admission.candidate.classification.value
            classification_counts[cls_value] = classification_counts.get(cls_value, 0) + 1
            batch_warnings.update(admission.warning_codes)
            if not admission.admitted:
                batch_reasons.update(admission.reason_codes)

        classes = set(classification_counts)
        has_public = bool(classes & PUBLIC_CLASSIFICATIONS)
        has_private = bool(classes & PRIVATE_CLASSIFICATIONS)
        has_unknown = ClassificationStatus.UNKNOWN.value in classes
        if has_private and has_public:
            batch_reasons.add("batch.mixed_private_public")
        if has_private:
            batch_reasons.add("batch.private_input")
        if has_unknown:
            batch_reasons.add("batch.unknown_classification")
        if has_private or has_unknown or (has_private and has_public):
            # Explicit privacy-reject signal used by staging callers.
            batch_reasons.add("privacy.rejected_before_staging")

        # Deterministic order by record_id for reproducible receipts.
        admissions_sorted = tuple(
            sorted(admissions, key=lambda item: item.candidate.record_id)
        )
        summary = {
            key: classification_counts[key] for key in sorted(classification_counts)
        }
        return BatchAdmission(
            admitted=not batch_reasons,
            reason_codes=tuple(sorted(batch_reasons)),
            warning_codes=tuple(sorted(batch_warnings)),
            record_admissions=admissions_sorted,
            classification_summary=summary,
            policy_sha256=self.policy_sha256,
        )


DEFAULT_RELEASE_POLICY: Final = PatentReleasePolicy()


def evaluate_record_admission(
    candidate: ReleaseCandidate | Mapping[str, Any],
) -> RecordAdmission:
    return DEFAULT_RELEASE_POLICY.evaluate_record(candidate)


def evaluate_batch_admission(
    candidates: Sequence[ReleaseCandidate | Mapping[str, Any]],
    *,
    expected_policy_sha256: str = RELEASE_POLICY_SHA256,
) -> BatchAdmission:
    return DEFAULT_RELEASE_POLICY.evaluate_batch(
        candidates, expected_policy_sha256=expected_policy_sha256
    )


def assert_public_batch(
    candidates: Sequence[ReleaseCandidate | Mapping[str, Any]],
) -> BatchAdmission:
    """Evaluate and require a fully admitted public batch (no staging side effects)."""

    return evaluate_batch_admission(candidates).require_admitted()


def _project_public_record(record: ReleaseCandidate) -> dict[str, Any]:
    """Project an admitted public row with full lineage and rights binding."""

    return {
        "artifact_kind": record.artifact_kind.value,
        "classification": record.classification.value,
        "payload": dict(record.payload),
        "policy_sha256": RELEASE_POLICY_SHA256,
        "policy_version": RELEASE_POLICY_VERSION,
        "record_id": record.record_id,
        "record_sha256": record.record_sha256,
        "rights_review": record.rights_review.to_dict(),
        "source_lineage": record.source_lineage.to_dict(),
    }


def _iter_text_fields(value: Any, *, prefix: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    if isinstance(value, str):
        results.append((prefix, value))
    elif isinstance(value, Mapping):
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}"
            results.extend(_iter_text_fields(value[key], prefix=child_prefix))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            results.extend(_iter_text_fields(item, prefix=f"{prefix}[{index}]"))
    return results


def _scan_detectors_on_text(
    field: str, value: str, *, max_field_chars: int
) -> list[PolicyFinding]:
    digest = _sha256_text(value)
    findings: list[PolicyFinding] = []
    scan_value = value
    if len(value) > max_field_chars:
        findings.append(
            PolicyFinding(
                category=FindingCategory.SCAN_LIMIT,
                code="scan.field_limit_exceeded",
                field=field,
                start_char=max_field_chars,
                end_char=len(value),
                value_sha256=digest,
            )
        )
        scan_value = value[:max_field_chars]
    for detector in _DETECTORS:
        for match in detector.pattern.finditer(scan_value):
            findings.append(
                PolicyFinding(
                    category=detector.category,
                    code=detector.code,
                    field=field,
                    start_char=match.start(),
                    end_char=match.end(),
                    value_sha256=digest,
                )
            )
            if len(findings) >= MAX_FINDINGS:
                return findings
    return findings


def _finding_sort_key(finding: PolicyFinding) -> tuple[Any, ...]:
    return (
        finding.category.value,
        finding.code,
        finding.field,
        finding.start_char,
        finding.end_char,
        finding.value_sha256,
    )


# Bind method using shared scanner helper.
def _policy_scan_text(self: PatentReleasePolicy, field: str, value: str) -> list[PolicyFinding]:
    return _scan_detectors_on_text(field, value, max_field_chars=self.max_field_chars)


PatentReleasePolicy._scan_text = _policy_scan_text  # type: ignore[method-assign]


__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_KIND_SET",
    "ALL_CLASSIFICATIONS",
    "ArtifactKind",
    "BatchAdmission",
    "ClassificationStatus",
    "DEFAULT_RELEASE_POLICY",
    "FindingCategory",
    "MAX_RECORDS_PER_BATCH",
    "PRIVATE_CLASSIFICATIONS",
    "PUBLIC_CLASSIFICATIONS",
    "PatentReleasePolicy",
    "PolicyFinding",
    "PrivacyRejectedError",
    "PublicationRejectedError",
    "RELEASE_POLICY_SHA256",
    "RELEASE_POLICY_VERSION",
    "RecordAdmission",
    "ReleaseCandidate",
    "ReleasePolicyError",
    "RightsReview",
    "RightsReviewStatus",
    "SourceLineage",
    "assert_public_batch",
    "evaluate_batch_admission",
    "evaluate_record_admission",
    "is_private_classification",
    "is_public_classification",
    "requires_quarantine",
]
