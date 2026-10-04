"""Deterministic governance and publication policy for CVEfixes derivatives.

All CVEfixes text, including text that resembles an instruction, is untrusted
data.  This module never executes, imports, renders as a prompt, or otherwise
interprets source bodies.  It only produces bounded findings, projections, and
non-authoritative admission receipts.

The default public profile publishes reviewed provenance and body digests, not
unrestricted third-party descriptions, messages, diffs, or code bodies.  The
internal profile can retain those bodies in access-controlled artifacts, but
uses the same secret, privacy, path, license, and policy-drift gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Pattern
from urllib.parse import urlsplit


RELEASE_POLICY_VERSION: Final = "cvefixes-release-policy/v1"
MAX_SCAN_FIELD_CHARS: Final = 8_388_608
MAX_FINDINGS: Final = 512

CVEFIXES_BODY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "commit_message",
        "cve_description",
        "cwe_description",
        "diff_with_context",
        "fixed_code",
        "vulnerable_code",
    }
)
CVEFIXES_PUBLIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "commit_date",
        "cve_id",
        "cvss2_base_score",
        "cvss3_base_score",
        "cwe_id",
        "cwe_name",
        "diff_stats",
        "file_paths",
        "hash",
        "language",
        "published_date",
        "repo_total_commits",
        "repo_total_files",
        "repo_url",
        "row_index",
        "security_keywords",
        "severity",
        "version_tag",
    }
)
CVEFIXES_RECORD_FIELDS: Final[frozenset[str]] = (
    CVEFIXES_BODY_FIELDS | CVEFIXES_PUBLIC_FIELDS
)


class ReleasePolicyError(ValueError):
    """Raised when release-policy input is malformed or unverifiable."""


class PublicationRejectedError(ReleasePolicyError):
    """Raised when a caller requires an admitted publication."""


class ReleaseVisibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"


class BodyTreatment(str, Enum):
    DIGEST_ONLY = "digest_only"
    FULL_RESTRICTED = "full_restricted"


class LicenseReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    REJECTED = "rejected"


class FindingCategory(str, Enum):
    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    PROMPT_INJECTION = "prompt_injection"
    UNSAFE_PATH = "unsafe_path"
    SCAN_LIMIT = "scan_limit"


@dataclass(frozen=True, slots=True)
class ReleaseProfile:
    """Immutable body-access profile applied before release staging."""

    name: str
    visibility: ReleaseVisibility
    body_treatment: BodyTreatment
    allowed_fields: frozenset[str]
    access_controlled: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ReleasePolicyError("profile name must be non-empty")
        if not isinstance(self.visibility, ReleaseVisibility):
            raise ReleasePolicyError("profile visibility is invalid")
        if not isinstance(self.body_treatment, BodyTreatment):
            raise ReleasePolicyError("profile body_treatment is invalid")
        if not isinstance(self.allowed_fields, frozenset) or not all(
            isinstance(item, str) and item for item in self.allowed_fields
        ):
            raise ReleasePolicyError(
                "profile allowed_fields must be a frozenset of names"
            )
        if not self.allowed_fields <= CVEFIXES_RECORD_FIELDS:
            raise ReleasePolicyError("profile contains unknown CVEfixes fields")
        if type(self.access_controlled) is not bool:
            raise ReleasePolicyError("profile access_controlled must be boolean")
        if self.visibility is ReleaseVisibility.PUBLIC:
            if self.body_treatment is not BodyTreatment.DIGEST_ONLY:
                raise ReleasePolicyError("public profiles must be digest-only")
            if self.allowed_fields & CVEFIXES_BODY_FIELDS:
                raise ReleasePolicyError(
                    "public profiles cannot include unrestricted full bodies"
                )
            if self.access_controlled:
                raise ReleasePolicyError(
                    "public profiles cannot claim access control"
                )
        elif (
            self.body_treatment is not BodyTreatment.FULL_RESTRICTED
            or not self.access_controlled
        ):
            raise ReleasePolicyError(
                "internal full-body profiles must be access controlled"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_controlled": self.access_controlled,
            "allowed_fields": sorted(self.allowed_fields),
            "body_treatment": self.body_treatment.value,
            "name": self.name,
            "visibility": self.visibility.value,
        }


PUBLIC_RELEASE_PROFILE: Final = ReleaseProfile(
    name="public-metadata-and-body-digests",
    visibility=ReleaseVisibility.PUBLIC,
    body_treatment=BodyTreatment.DIGEST_ONLY,
    allowed_fields=CVEFIXES_PUBLIC_FIELDS,
    access_controlled=False,
)
INTERNAL_RELEASE_PROFILE: Final = ReleaseProfile(
    name="internal-restricted-full-bodies",
    visibility=ReleaseVisibility.INTERNAL,
    body_treatment=BodyTreatment.FULL_RESTRICTED,
    allowed_fields=CVEFIXES_RECORD_FIELDS,
    access_controlled=True,
)
DEFAULT_RELEASE_PROFILE: Final = PUBLIC_RELEASE_PROFILE


@dataclass(frozen=True, slots=True)
class LicenseProvenance:
    """Reviewed license evidence bound to an immutable source revision."""

    dataset_id: str
    source_revision: str
    license_expression: str
    evidence_url: str
    review_status: LicenseReviewStatus
    reviewed_by: str
    reviewed_at: str
    redistribution_allowed: bool

    def __post_init__(self) -> None:
        for label in (
            "dataset_id",
            "source_revision",
            "license_expression",
            "evidence_url",
        ):
            value = getattr(self, label)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ReleasePolicyError(f"{label} must be non-empty trimmed text")
        parsed_url = urlsplit(self.evidence_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ReleasePolicyError("evidence_url must be an absolute HTTPS URL")
        if not isinstance(self.review_status, LicenseReviewStatus):
            raise ReleasePolicyError("license review_status is invalid")
        if type(self.redistribution_allowed) is not bool:
            raise ReleasePolicyError(
                "redistribution_allowed must be boolean"
            )
        if self.review_status is LicenseReviewStatus.REVIEWED:
            if not isinstance(self.reviewed_by, str) or not self.reviewed_by.strip():
                raise ReleasePolicyError(
                    "reviewed license provenance requires reviewed_by"
                )
            if not _RFC3339_UTC_RE.fullmatch(self.reviewed_at):
                raise ReleasePolicyError(
                    "reviewed license provenance requires RFC3339 UTC reviewed_at"
                )
        elif self.reviewed_by or self.reviewed_at:
            raise ReleasePolicyError(
                "unreviewed/rejected provenance cannot claim review metadata"
            )

    @property
    def reviewed_for_release(self) -> bool:
        return (
            self.review_status is LicenseReviewStatus.REVIEWED
            and self.redistribution_allowed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "evidence_url": self.evidence_url,
            "license_expression": self.license_expression,
            "redistribution_allowed": self.redistribution_allowed,
            "review_status": self.review_status.value,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LicenseProvenance":
        _require_exact_keys(
            value,
            {
                "dataset_id",
                "evidence_url",
                "license_expression",
                "redistribution_allowed",
                "review_status",
                "reviewed_at",
                "reviewed_by",
                "source_revision",
            },
            "license provenance",
        )
        try:
            status = LicenseReviewStatus(value["review_status"])
        except (TypeError, ValueError) as exc:
            raise ReleasePolicyError("license review_status is invalid") from exc
        return cls(
            dataset_id=value["dataset_id"],
            source_revision=value["source_revision"],
            license_expression=value["license_expression"],
            evidence_url=value["evidence_url"],
            review_status=status,
            reviewed_by=value["reviewed_by"],
            reviewed_at=value["reviewed_at"],
            redistribution_allowed=value["redistribution_allowed"],
        )


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """A bounded location and code; matched sensitive text is never retained."""

    category: FindingCategory
    code: str
    field: str
    start_char: int
    end_char: int
    value_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, FindingCategory):
            raise ReleasePolicyError("finding category is invalid")
        if not isinstance(self.code, str) or not self.code:
            raise ReleasePolicyError("finding code must be non-empty")
        if not isinstance(self.field, str) or not self.field:
            raise ReleasePolicyError("finding field must be non-empty")
        if (
            type(self.start_char) is not int
            or type(self.end_char) is not int
            or self.start_char < 0
            or self.end_char < self.start_char
        ):
            raise ReleasePolicyError("finding offsets are invalid")
        _require_sha256(self.value_sha256, "finding value_sha256")

    @property
    def blocks_release(self) -> bool:
        return self.category in {
            FindingCategory.SECRET,
            FindingCategory.UNSAFE_PATH,
            FindingCategory.SCAN_LIMIT,
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
class PolicyScanReport:
    """Complete bounded scan result tied to record content and policy."""

    record_sha256: str
    policy_sha256: str
    fields_scanned: tuple[str, ...]
    findings: tuple[PolicyFinding, ...]
    policy_version: str = RELEASE_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.record_sha256, "scan record_sha256")
        _require_sha256(self.policy_sha256, "scan policy_sha256")
        if self.policy_version != RELEASE_POLICY_VERSION:
            raise ReleasePolicyError("scan policy_version is unsupported")
        if self.fields_scanned != tuple(sorted(set(self.fields_scanned))):
            raise ReleasePolicyError(
                "scan fields_scanned must be sorted and unique"
            )
        if self.findings != tuple(sorted(self.findings, key=_finding_sort_key)):
            raise ReleasePolicyError("scan findings must be deterministically sorted")

    def findings_for(
        self, category: FindingCategory
    ) -> tuple[PolicyFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.category is category
        )

    @property
    def secret_findings(self) -> tuple[PolicyFinding, ...]:
        return self.findings_for(FindingCategory.SECRET)

    @property
    def personal_data_findings(self) -> tuple[PolicyFinding, ...]:
        return self.findings_for(FindingCategory.PERSONAL_DATA)

    @property
    def prompt_injection_findings(self) -> tuple[PolicyFinding, ...]:
        return self.findings_for(FindingCategory.PROMPT_INJECTION)

    @property
    def unsafe_path_findings(self) -> tuple[PolicyFinding, ...]:
        return self.findings_for(FindingCategory.UNSAFE_PATH)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields_scanned": list(self.fields_scanned),
            "findings": [item.to_dict() for item in self.findings],
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "record_sha256": self.record_sha256,
        }


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    """Canonical proof that sensitive spans were replaced, not silently lost."""

    field: str
    source_sha256: str
    output_sha256: str
    finding_codes: tuple[str, ...]
    policy_sha256: str
    method: str = "deterministic-span-redaction/v1"
    policy_version: str = RELEASE_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field:
            raise ReleasePolicyError("redaction field must be non-empty")
        _require_sha256(self.source_sha256, "redaction source_sha256")
        _require_sha256(self.output_sha256, "redaction output_sha256")
        _require_sha256(self.policy_sha256, "redaction policy_sha256")
        if self.source_sha256 == self.output_sha256:
            raise ReleasePolicyError("redaction must change the field content")
        if (
            not self.finding_codes
            or self.finding_codes != tuple(sorted(set(self.finding_codes)))
        ):
            raise ReleasePolicyError(
                "redaction finding_codes must be sorted, unique, and non-empty"
            )
        if self.method != "deterministic-span-redaction/v1":
            raise ReleasePolicyError("redaction method is unsupported")
        if self.policy_version != RELEASE_POLICY_VERSION:
            raise ReleasePolicyError("redaction policy_version is unsupported")

    @property
    def receipt_id(self) -> str:
        return _sha256_json(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        value = {
            "field": self.field,
            "finding_codes": list(self.finding_codes),
            "method": self.method,
            "output_sha256": self.output_sha256,
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "source_sha256": self.source_sha256,
        }
        if include_id:
            value["receipt_id"] = self.receipt_id
        return value


@dataclass(frozen=True, slots=True)
class PublicationAdmission:
    """Non-authoritative result of applying the local release policy."""

    admitted: bool
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    profile: ReleaseProfile
    policy_sha256: str
    license_provenance: LicenseProvenance
    scan_report: PolicyScanReport
    projected_record: Mapping[str, Any]
    redaction_receipts: tuple[RedactionReceipt, ...] = ()
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
        _require_sha256(self.policy_sha256, "admission policy_sha256")
        object.__setattr__(
            self, "projected_record", _freeze_json_mapping(self.projected_record)
        )

    @property
    def admission_id(self) -> str:
        return _sha256_json(self.to_dict(include_id=False))

    def require_admitted(self) -> "PublicationAdmission":
        if not self.admitted:
            raise PublicationRejectedError(
                "publication rejected: " + ", ".join(self.reason_codes)
            )
        return self

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        value = {
            "admitted": self.admitted,
            "license_provenance": self.license_provenance.to_dict(),
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "profile": self.profile.to_dict(),
            "projected_record": _thaw_json(self.projected_record),
            "reason_codes": list(self.reason_codes),
            "redaction_receipts": [
                receipt.to_dict() for receipt in self.redaction_receipts
            ],
            "scan_report": self.scan_report.to_dict(),
            "warning_codes": list(self.warning_codes),
        }
        if include_id:
            value["admission_id"] = self.admission_id
        return value


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
        "secret.api_token",
        _pattern(
            r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
            r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
        ),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.assigned_credential",
        _pattern(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|password|secret[_-]?key)\b\s*[:=]\s*[\"']?"
            r"(?!example\b|placeholder\b|redacted\b|changeme\b|<)"
            r"[A-Za-z0-9/+_.:@-]{12,}"
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
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.phone",
        _pattern(
            r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})"
            r"[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "poisoning.ignore_instructions",
        _pattern(
            r"\b(?:(?:ignore|disregard|forget)\s+(?:all\s+)?|"
            r"do\s+not\s+(?:obey|follow)\s+)"
            r"(?:previous|prior|above|earlier|system|developer)\s+instructions?\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "poisoning.prompt_exfiltration",
        _pattern(
            r"\b(?:reveal|print|show|leak|repeat)\s+(?:the\s+|your\s+)?"
            r"(?:hidden\s+)?(?:system|developer)\s+"
            r"(?:prompt|message|instructions?)\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "poisoning.tool_directive",
        _pattern(
            r"(?:<\s*(?:tool[_ -]?call|function_calls?)\b|"
            r"[\"']tool_calls?[\"']\s*:|"
            r"\b(?:assistant\s+to|recipient)\s*=\s*(?:functions|tools)\.)"
        ),
    ),
)

_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SENSITIVE_ARTIFACT_PARTS = frozenset(
    {
        ".env",
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "credentials",
        "internal",
        "private",
        "secrets",
    }
)

_POLICY_MANIFEST = {
    "body_fields": sorted(CVEFIXES_BODY_FIELDS),
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
    "max_scan_field_chars": MAX_SCAN_FIELD_CHARS,
    "profiles": [
        INTERNAL_RELEASE_PROFILE.to_dict(),
        PUBLIC_RELEASE_PROFILE.to_dict(),
    ],
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


class CVEfixesReleasePolicy:
    """Side-effect-free scanner, projector, and publication admission gate."""

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

    def scan_record(self, record: Mapping[str, Any]) -> PolicyScanReport:
        """Scan one normalized row without retaining any matched value."""

        normalized = _validated_record(record)
        findings: list[PolicyFinding] = []
        fields_scanned: set[str] = set()
        for field in sorted(normalized):
            for value in _text_values(normalized[field]):
                fields_scanned.add(field)
                findings.extend(self._scan_text(field, value))
                if len(findings) >= MAX_FINDINGS:
                    findings = findings[:MAX_FINDINGS]
                    findings.append(
                        PolicyFinding(
                            category=FindingCategory.SCAN_LIMIT,
                            code="scan.finding_limit_exceeded",
                            field=field,
                            start_char=0,
                            end_char=len(value),
                            value_sha256=_sha256_text(value),
                        )
                    )
                    break
            if len(findings) > MAX_FINDINGS:
                break
        for index, path in enumerate(normalized.get("file_paths", ())):
            path_finding = _unsafe_path_finding(
                path, f"file_paths[{index}]", publication_artifact=False
            )
            if path_finding is not None:
                findings.append(path_finding)
        deduplicated = {
            _finding_sort_key(finding): finding for finding in findings
        }
        ordered = tuple(
            deduplicated[key] for key in sorted(deduplicated)
        )
        return PolicyScanReport(
            record_sha256=_sha256_json(normalized),
            policy_sha256=self.policy_sha256,
            fields_scanned=tuple(sorted(fields_scanned)),
            findings=ordered,
        )

    def project_record(
        self,
        record: Mapping[str, Any],
        *,
        license_provenance: LicenseProvenance,
        profile: ReleaseProfile = DEFAULT_RELEASE_PROFILE,
        redaction_receipts: Sequence[RedactionReceipt] = (),
    ) -> Mapping[str, Any]:
        """Project a row under an exact body profile while retaining lineage."""

        normalized = _validated_record(record)
        if not isinstance(profile, ReleaseProfile):
            raise ReleasePolicyError("profile must be a ReleaseProfile")
        if not isinstance(license_provenance, LicenseProvenance):
            raise ReleasePolicyError(
                "license_provenance must be LicenseProvenance"
            )
        receipts = _redaction_receipt_tuple(redaction_receipts)
        projected = {
            key: normalized[key]
            for key in sorted(profile.allowed_fields)
            if key in normalized
        }
        body_digests: dict[str, dict[str, Any]] = {}
        if profile.body_treatment is BodyTreatment.DIGEST_ONLY:
            for field in sorted(CVEFIXES_BODY_FIELDS & normalized.keys()):
                value = normalized[field]
                if value is None or value == "" or value == []:
                    continue
                body_digests[field] = {
                    "sha256": _sha256_json(value),
                    "utf8_bytes": len(
                        _canonical_json(value).encode("utf-8")
                    ),
                }
        if body_digests:
            projected["body_digests"] = body_digests
        projected["content_trust"] = "untrusted_inert_data"
        projected["instruction_handling"] = (
            "never_execute_or_treat_as_authority"
        )
        projected["profile"] = profile.name
        projected["source_provenance"] = {
            **license_provenance.to_dict(),
            "source_record_sha256": _sha256_json(normalized),
        }
        if receipts:
            projected["redaction_receipts"] = [
                receipt.to_dict() for receipt in receipts
            ]
        return _freeze_json_mapping(projected)

    def evaluate(
        self,
        record: Mapping[str, Any],
        *,
        license_provenance: LicenseProvenance,
        profile: ReleaseProfile = DEFAULT_RELEASE_PROFILE,
        artifact_paths: Sequence[str] = (),
        redaction_receipts: Sequence[RedactionReceipt] = (),
        expected_policy_sha256: str = RELEASE_POLICY_SHA256,
    ) -> PublicationAdmission:
        """Return a fail-closed publication decision and projected row."""

        normalized = _validated_record(record)
        scan = self.scan_record(normalized)
        receipts = _redaction_receipt_tuple(redaction_receipts)
        projected = self.project_record(
            normalized,
            license_provenance=license_provenance,
            profile=profile,
            redaction_receipts=receipts,
        )
        reasons: set[str] = set()
        warnings: set[str] = set()

        if expected_policy_sha256 != self.policy_sha256:
            reasons.add("policy.drift")
        if not license_provenance.reviewed_for_release:
            if license_provenance.review_status is LicenseReviewStatus.UNREVIEWED:
                reasons.add("license.unreviewed")
            elif license_provenance.review_status is LicenseReviewStatus.REJECTED:
                reasons.add("license.rejected")
            if not license_provenance.redistribution_allowed:
                reasons.add("license.redistribution_not_allowed")

        for receipt in receipts:
            if (
                receipt.policy_sha256 != self.policy_sha256
                or receipt.policy_version != RELEASE_POLICY_VERSION
                or not _receipt_matches_record_output(receipt, normalized)
            ):
                reasons.add("redaction.receipt_invalid_or_stale")
            if any(code.startswith("secret.") for code in receipt.finding_codes):
                # A redacted derivative may be retained for incident handling,
                # but a candidate known to have contained a secret is not
                # eligible for this publication admission.
                reasons.add("content.secret_detected")

        for finding in scan.findings:
            if finding.category is FindingCategory.SECRET:
                reasons.add("content.secret_detected")
            elif finding.category is FindingCategory.UNSAFE_PATH:
                reasons.add("path.unsafe")
            elif finding.category is FindingCategory.SCAN_LIMIT:
                reasons.add("scan.incomplete")
            elif finding.category is FindingCategory.PROMPT_INJECTION:
                warnings.add("content.prompt_injection_inert")
            elif finding.category is FindingCategory.PERSONAL_DATA:
                if (
                    profile.body_treatment is BodyTreatment.DIGEST_ONLY
                    and finding.field in CVEFIXES_BODY_FIELDS
                ):
                    warnings.add("privacy.personal_data_body_omitted")
                else:
                    reasons.add("privacy.personal_data_unredacted")

        for index, path in enumerate(_string_sequence(artifact_paths, "artifact_paths")):
            finding = _unsafe_path_finding(
                path, f"artifact_paths[{index}]", publication_artifact=True
            )
            if finding is not None:
                reasons.add("path.unsafe")

        return PublicationAdmission(
            admitted=not reasons,
            reason_codes=tuple(sorted(reasons)),
            warning_codes=tuple(sorted(warnings)),
            profile=profile,
            policy_sha256=self.policy_sha256,
            license_provenance=license_provenance,
            scan_report=scan,
            projected_record=projected,
            redaction_receipts=receipts,
        )

    evaluate_release = evaluate

    def _scan_text(self, field: str, value: str) -> list[PolicyFinding]:
        digest = _sha256_text(value)
        findings: list[PolicyFinding] = []
        if len(value) > self.max_field_chars:
            findings.append(
                PolicyFinding(
                    category=FindingCategory.SCAN_LIMIT,
                    code="scan.field_limit_exceeded",
                    field=field,
                    start_char=self.max_field_chars,
                    end_char=len(value),
                    value_sha256=digest,
                )
            )
            value = value[: self.max_field_chars]
        for detector in _DETECTORS:
            for match in detector.pattern.finditer(value):
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


DEFAULT_RELEASE_POLICY: Final = CVEfixesReleasePolicy()


def scan_release_record(record: Mapping[str, Any]) -> PolicyScanReport:
    """Scan one row under the default current policy."""

    return DEFAULT_RELEASE_POLICY.scan_record(record)


def project_release_record(
    record: Mapping[str, Any],
    *,
    license_provenance: LicenseProvenance,
    profile: ReleaseProfile = DEFAULT_RELEASE_PROFILE,
    redaction_receipts: Sequence[RedactionReceipt] = (),
) -> Mapping[str, Any]:
    """Project one row under a deterministic body profile."""

    return DEFAULT_RELEASE_POLICY.project_record(
        record,
        license_provenance=license_provenance,
        profile=profile,
        redaction_receipts=redaction_receipts,
    )


def evaluate_publication_admission(
    record: Mapping[str, Any],
    *,
    license_provenance: LicenseProvenance,
    profile: ReleaseProfile = DEFAULT_RELEASE_PROFILE,
    artifact_paths: Sequence[str] = (),
    redaction_receipts: Sequence[RedactionReceipt] = (),
    expected_policy_sha256: str = RELEASE_POLICY_SHA256,
) -> PublicationAdmission:
    """Evaluate and project one record with the default current policy."""

    return DEFAULT_RELEASE_POLICY.evaluate(
        record,
        license_provenance=license_provenance,
        profile=profile,
        artifact_paths=artifact_paths,
        redaction_receipts=redaction_receipts,
        expected_policy_sha256=expected_policy_sha256,
    )


def redact_sensitive_text(
    text: str,
    *,
    field: str,
    policy: CVEfixesReleasePolicy = DEFAULT_RELEASE_POLICY,
) -> tuple[str, RedactionReceipt]:
    """Redact detected secret/PII spans and emit a content-bound receipt.

    Prompt-injection findings are intentionally not rewritten: callers must
    keep source text in an inert data channel, and public bodies are omitted by
    the default profile.  A secret finding remains release-blocking even if a
    redacted derivative exists, so leaked source is never silently laundered.
    """

    if not isinstance(text, str):
        raise ReleasePolicyError("redaction text must be a string")
    if not isinstance(field, str) or not field:
        raise ReleasePolicyError("redaction field must be non-empty")
    findings = [
        finding
        for finding in policy._scan_text(field, text)
        if finding.category
        in {FindingCategory.SECRET, FindingCategory.PERSONAL_DATA}
    ]
    if not findings:
        raise ReleasePolicyError("redaction requires a secret or PII finding")
    spans = _merge_redaction_spans(findings)
    pieces: list[str] = []
    cursor = 0
    for start, end, categories in spans:
        pieces.append(text[cursor:start])
        label = (
            "SECRET"
            if FindingCategory.SECRET in categories
            else "PERSONAL_DATA"
        )
        pieces.append(f"[REDACTED:{label}]")
        cursor = end
    pieces.append(text[cursor:])
    redacted = "".join(pieces)
    receipt = RedactionReceipt(
        field=field,
        source_sha256=_sha256_text(text),
        output_sha256=_sha256_text(redacted),
        finding_codes=tuple(sorted({item.code for item in findings})),
        policy_sha256=policy.policy_sha256,
    )
    return redacted, receipt


def _validated_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ReleasePolicyError("release record must be a mapping")
    unknown = sorted(set(record) - CVEFIXES_RECORD_FIELDS)
    if unknown:
        raise ReleasePolicyError(
            "release record has unknown field(s): " + ", ".join(unknown)
        )
    try:
        encoded = _canonical_json(record)
        normalized = json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReleasePolicyError(
            "release record must contain finite JSON-compatible values"
        ) from exc
    if not isinstance(normalized, dict):
        raise ReleasePolicyError("release record must encode as an object")
    paths = normalized.get("file_paths", [])
    if paths is not None:
        normalized["file_paths"] = list(_string_sequence(paths, "file_paths"))
    return normalized


def _text_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        result: list[str] = []
        for key in sorted(value):
            result.extend(_text_values(value[key]))
        return tuple(result)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = []
        for item in value:
            result.extend(_text_values(item))
        return tuple(result)
    return ()


def _unsafe_path_finding(
    path: str, field: str, *, publication_artifact: bool
) -> PolicyFinding | None:
    unsafe = False
    try:
        parsed = PurePosixPath(path)
    except (TypeError, ValueError):
        unsafe = True
        parsed = PurePosixPath(".")
    parts = parsed.parts
    if (
        not isinstance(path, str)
        or not path
        or "\x00" in path
        or "\\" in path
        or path.startswith("/")
        or path != path.strip()
        or "//" in path
        or any(part in {"", ".", ".."} for part in parts)
        or _WINDOWS_DRIVE_RE.match(path)
        or urlsplit(path).scheme
    ):
        unsafe = True
    if publication_artifact and any(
        part.casefold() in _SENSITIVE_ARTIFACT_PARTS for part in parts
    ):
        unsafe = True
    if not unsafe:
        return None
    return PolicyFinding(
        category=FindingCategory.UNSAFE_PATH,
        code=(
            "path.unsafe_publication_artifact"
            if publication_artifact
            else "path.unsafe_source"
        ),
        field=field,
        start_char=0,
        end_char=len(path) if isinstance(path, str) else 0,
        value_sha256=_sha256_text(path if isinstance(path, str) else repr(path)),
    )


def _receipt_matches_record_output(
    receipt: RedactionReceipt, record: Mapping[str, Any]
) -> bool:
    value = record.get(receipt.field)
    return isinstance(value, str) and _sha256_text(value) == receipt.output_sha256


def _redaction_receipt_tuple(
    value: Sequence[RedactionReceipt],
) -> tuple[RedactionReceipt, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise ReleasePolicyError("redaction_receipts must be a sequence")
    result = tuple(value)
    if not all(isinstance(item, RedactionReceipt) for item in result):
        raise ReleasePolicyError(
            "redaction_receipts must contain RedactionReceipt values"
        )
    if len({item.receipt_id for item in result}) != len(result):
        raise ReleasePolicyError("redaction_receipts must not contain duplicates")
    return tuple(sorted(result, key=lambda item: item.receipt_id))


def _merge_redaction_spans(
    findings: Sequence[PolicyFinding],
) -> tuple[tuple[int, int, frozenset[FindingCategory]], ...]:
    ordered = sorted(
        (
            finding.start_char,
            finding.end_char,
            finding.category,
        )
        for finding in findings
    )
    merged: list[tuple[int, int, set[FindingCategory]]] = []
    for start, end, category in ordered:
        if merged and start <= merged[-1][1]:
            old_start, old_end, categories = merged[-1]
            categories.add(category)
            merged[-1] = (old_start, max(old_end, end), categories)
        else:
            merged.append((start, end, {category}))
    return tuple(
        (start, end, frozenset(categories))
        for start, end, categories in merged
    )


def _string_sequence(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise ReleasePolicyError(f"{label} must be a sequence of strings")
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise ReleasePolicyError(
            f"{label} must contain non-empty strings"
        )
    return result


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise ReleasePolicyError(f"{label} must be a mapping")
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unexpected=" + ",".join(unknown))
        raise ReleasePolicyError(f"{label} fields invalid: {'; '.join(details)}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ReleasePolicyError(f"{label} must be lowercase SHA-256")
    return value


def _finding_sort_key(finding: PolicyFinding) -> tuple[Any, ...]:
    return (
        finding.field,
        finding.start_char,
        finding.end_char,
        finding.category.value,
        finding.code,
        finding.value_sha256,
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_json_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze_json(dict(value))


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


__all__ = [
    "BodyTreatment",
    "CVEFIXES_BODY_FIELDS",
    "CVEfixesReleasePolicy",
    "DEFAULT_RELEASE_POLICY",
    "DEFAULT_RELEASE_PROFILE",
    "FindingCategory",
    "INTERNAL_RELEASE_PROFILE",
    "LicenseProvenance",
    "LicenseReviewStatus",
    "PUBLIC_RELEASE_PROFILE",
    "PolicyFinding",
    "PolicyScanReport",
    "PublicationAdmission",
    "PublicationRejectedError",
    "RELEASE_POLICY_SHA256",
    "RELEASE_POLICY_VERSION",
    "RedactionReceipt",
    "ReleasePolicyError",
    "ReleaseProfile",
    "ReleaseVisibility",
    "evaluate_publication_admission",
    "project_release_record",
    "redact_sensitive_text",
    "scan_release_record",
]
