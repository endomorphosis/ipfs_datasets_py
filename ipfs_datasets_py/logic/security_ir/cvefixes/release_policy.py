"""Fail-closed governance policy for CVEfixes-derived releases.

This module treats every source body as inert, untrusted data.  It only scans
strings and constructs immutable decisions: it never renders source text into
a prompt, imports source code, follows a URL, opens an output path, or grants
execution authority.

The default public profile permits metadata and bounded excerpts, but never a
complete third-party body.  Full bodies are reserved for the explicit
internal profile.  Both profiles require reviewed license provenance, safe
relative output paths, a current policy digest, and clean released content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Mapping, Pattern, Sequence

from ...ir_core.canonical import canonical_json_bytes


RELEASE_POLICY_VERSION: Final = "cvefixes-release-policy/v1"
REDACTION_RECEIPT_VERSION: Final = "cvefixes-redaction-receipt/v1"
PUBLIC_PROFILE_ID: Final = "public-bounded/v1"
INTERNAL_PROFILE_ID: Final = "internal-reviewed/v1"
INERT_SOURCE_TREATMENT: Final = "inert-untrusted-data/v1"
DEFAULT_MAX_SCAN_CHARS: Final = 1_000_000
DEFAULT_PUBLIC_EXCERPT_CHARS: Final = 4_096
MAX_FINDINGS_PER_PATTERN: Final = 64

DEFAULT_APPROVED_LICENSES: Final[tuple[str, ...]] = (
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC-BY-4.0",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MIT-0",
    "MPL-2.0",
    "Python-2.0",
    "Unlicense",
    "Zlib",
)

_FORBIDDEN_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        "private",
        "secrets",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_REDACTION_MARKER_RE = re.compile(r"\[REDACTED:[a-z0-9_.-]+\]")


class ReleasePolicyError(ValueError):
    """Raised when a release-policy contract is malformed."""


class ReleaseAudience(str, Enum):
    """Who may receive artifacts governed by a body profile."""

    PUBLIC = "public"
    INTERNAL = "internal"


class BodyMode(str, Enum):
    """Maximum source-body exposure permitted by a profile."""

    OMIT = "omit"
    BOUNDED_EXCERPTS = "bounded_excerpts"
    FULL = "full"


class FindingCategory(str, Enum):
    """Classes found by bounded, side-effect-free source scanners."""

    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    PROMPT_INJECTION = "prompt_injection"
    SCAN_BOUND = "scan_bound"


class AdmissionDecision(str, Enum):
    """Publication admission result."""

    ADMIT = "admit"
    REJECT = "reject"


def _require_text(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ReleasePolicyError(
            f"{field_name} must be a non-empty trimmed text value without controls"
        )
    return value


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReleasePolicyError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_digest(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(canonical_json_bytes(value))


def _require_utc_timestamp(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not text.endswith("Z"):
        raise ReleasePolicyError(f"{field_name} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ReleasePolicyError(
            f"{field_name} must be an RFC 3339 UTC timestamp"
        ) from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ReleasePolicyError(f"{field_name} must be an RFC 3339 UTC timestamp")
    return text


def _normalize_license_expression(value: str) -> str:
    return " ".join(_require_text(value, "license expression").split()).casefold()


@dataclass(frozen=True, slots=True)
class BodyProfile:
    """Reviewed limit on source-body material for one release audience."""

    profile_id: str
    audience: ReleaseAudience
    body_mode: BodyMode
    max_excerpt_chars: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_id", _require_text(self.profile_id, "profile_id")
        )
        try:
            object.__setattr__(self, "audience", ReleaseAudience(self.audience))
            object.__setattr__(self, "body_mode", BodyMode(self.body_mode))
        except ValueError as exc:
            raise ReleasePolicyError("unsupported body profile value") from exc
        if (
            isinstance(self.max_excerpt_chars, bool)
            or not isinstance(self.max_excerpt_chars, int)
            or self.max_excerpt_chars < 0
        ):
            raise ReleasePolicyError("max_excerpt_chars must be a non-negative integer")
        if self.body_mode is BodyMode.BOUNDED_EXCERPTS:
            if self.max_excerpt_chars < 1:
                raise ReleasePolicyError(
                    "bounded-excerpt profiles require a positive character limit"
                )
        elif self.max_excerpt_chars != 0:
            raise ReleasePolicyError(
                "max_excerpt_chars is only valid for bounded-excerpt profiles"
            )
        if (
            self.audience is ReleaseAudience.PUBLIC
            and self.body_mode is BodyMode.FULL
        ):
            raise ReleasePolicyError("public profiles cannot permit full bodies")

    def to_dict(self) -> dict[str, Any]:
        return {
            "audience": self.audience.value,
            "body_mode": self.body_mode.value,
            "max_excerpt_chars": self.max_excerpt_chars,
            "profile_id": self.profile_id,
        }


DEFAULT_PUBLIC_PROFILE: Final = BodyProfile(
    profile_id=PUBLIC_PROFILE_ID,
    audience=ReleaseAudience.PUBLIC,
    body_mode=BodyMode.BOUNDED_EXCERPTS,
    max_excerpt_chars=DEFAULT_PUBLIC_EXCERPT_CHARS,
)
DEFAULT_INTERNAL_PROFILE: Final = BodyProfile(
    profile_id=INTERNAL_PROFILE_ID,
    audience=ReleaseAudience.INTERNAL,
    body_mode=BodyMode.FULL,
)


@dataclass(frozen=True, slots=True)
class LicenseProvenance:
    """Source-bound license declaration and optional human review binding."""

    expression: str
    source_dataset: str
    source_revision: str
    source_url: str
    source_path: str
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_digest: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "expression",
            "source_dataset",
            "source_revision",
            "source_url",
            "source_path",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )
        review_values = (self.reviewed_by, self.reviewed_at, self.review_digest)
        if any(review_values) and not all(review_values):
            raise ReleasePolicyError(
                "license review requires reviewed_by, reviewed_at, and review_digest"
            )
        if all(review_values):
            object.__setattr__(
                self,
                "reviewed_by",
                _require_text(self.reviewed_by, "reviewed_by"),
            )
            object.__setattr__(
                self,
                "reviewed_at",
                _require_utc_timestamp(self.reviewed_at, "reviewed_at"),
            )
            object.__setattr__(
                self,
                "review_digest",
                _require_sha256(self.review_digest, "review_digest"),
            )

    @property
    def review_payload(self) -> dict[str, str]:
        return {
            "expression": self.expression,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "source_dataset": self.source_dataset,
            "source_path": self.source_path,
            "source_revision": self.source_revision,
            "source_url": self.source_url,
        }

    @property
    def expected_review_digest(self) -> str:
        if not self.reviewed_by or not self.reviewed_at:
            return ""
        return _canonical_digest(self.review_payload)

    @property
    def reviewed(self) -> bool:
        """Whether the complete provenance tuple has a valid review binding."""

        return bool(
            self.review_digest
            and self.review_digest == self.expected_review_digest
        )

    @classmethod
    def reviewed_provenance(
        cls,
        *,
        expression: str,
        source_dataset: str,
        source_revision: str,
        source_url: str,
        source_path: str,
        reviewed_by: str,
        reviewed_at: str,
    ) -> "LicenseProvenance":
        """Construct provenance whose review digest binds every source field."""

        provisional = cls(
            expression=expression,
            source_dataset=source_dataset,
            source_revision=source_revision,
            source_url=source_url,
            source_path=source_path,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            review_digest="0" * 64,
        )
        return cls(
            expression=provisional.expression,
            source_dataset=provisional.source_dataset,
            source_revision=provisional.source_revision,
            source_url=provisional.source_url,
            source_path=provisional.source_path,
            reviewed_by=provisional.reviewed_by,
            reviewed_at=provisional.reviewed_at,
            review_digest=provisional.expected_review_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "review_digest": self.review_digest,
            "reviewed": self.reviewed,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "source_dataset": self.source_dataset,
            "source_path": self.source_path,
            "source_revision": self.source_revision,
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """A bounded pointer to sensitive or hostile data.

    Matching text is deliberately absent so findings and logs cannot copy a
    credential or personal identifier.
    """

    category: FindingCategory
    code: str
    field: str
    start_char: int
    end_char: int

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "category", FindingCategory(self.category))
        except ValueError as exc:
            raise ReleasePolicyError("unsupported finding category") from exc
        object.__setattr__(self, "code", _require_text(self.code, "finding code"))
        if not isinstance(self.field, str) or not _SAFE_FIELD_RE.fullmatch(self.field):
            raise ReleasePolicyError("finding field is not a safe field identifier")
        if (
            isinstance(self.start_char, bool)
            or not isinstance(self.start_char, int)
            or isinstance(self.end_char, bool)
            or not isinstance(self.end_char, int)
            or self.start_char < 0
            or self.end_char <= self.start_char
        ):
            raise ReleasePolicyError("finding character bounds are invalid")

    @property
    def blocks_publication(self) -> bool:
        return self.category is not FindingCategory.PROMPT_INJECTION

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_publication": self.blocks_publication,
            "category": self.category.value,
            "code": self.code,
            "end_char": self.end_char,
            "field": self.field,
            "start_char": self.start_char,
        }


@dataclass(frozen=True, slots=True)
class _Detector:
    category: FindingCategory
    code: str
    pattern: Pattern[str]


def _pattern(value: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Pattern[str]:
    return re.compile(value, flags)


_DETECTORS: Final[tuple[_Detector, ...]] = (
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
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
            r"password|secret[_-]?key)\b[ \t]*[:=][ \t]*[\"']?"
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
        "hostile.ignore_instructions",
        _pattern(
            r"\b(?:(?:ignore|disregard|forget)\s+(?:all\s+)?|"
            r"do\s+not\s+(?:obey|follow)\s+)"
            r"(?:previous|prior|above|earlier|system|developer)\s+instructions?\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.prompt_exfiltration",
        _pattern(
            r"\b(?:reveal|print|show|leak|repeat)\s+(?:the\s+|your\s+)?"
            r"(?:hidden\s+)?(?:system|developer)\s+(?:prompt|message|instructions?)\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.tool_directive",
        _pattern(
            r"(?:<\s*(?:tool[_ -]?call|function_calls?)\b|"
            r"\b(?:call|invoke|execute|run)\s+(?:the\s+)?"
            r"(?:shell|terminal|command|tool|function)\b|"
            r"\b(?:curl|wget)\b[^\r\n|]{0,500}\|\s*(?:ba|z|k)?sh\b)"
        ),
    ),
)


def scan_release_text(
    field: str,
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_SCAN_CHARS,
) -> tuple[ScanFinding, ...]:
    """Scan one inert text value without evaluating or executing it."""

    if not isinstance(field, str) or not _SAFE_FIELD_RE.fullmatch(field):
        raise ReleasePolicyError("field is not a safe field identifier")
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars < 1
    ):
        raise ReleasePolicyError("max_chars must be a positive integer")

    findings: list[ScanFinding] = []
    scanned = text[:max_chars]
    for detector in _DETECTORS:
        for match in list(detector.pattern.finditer(scanned))[
            :MAX_FINDINGS_PER_PATTERN
        ]:
            findings.append(
                ScanFinding(
                    category=detector.category,
                    code=detector.code,
                    field=field,
                    start_char=match.start(),
                    end_char=match.end(),
                )
            )
    if len(text) > max_chars:
        findings.append(
            ScanFinding(
                category=FindingCategory.SCAN_BOUND,
                code="scan.limit_exceeded",
                field=field,
                start_char=max_chars,
                end_char=max_chars + 1,
            )
        )
    return tuple(
        sorted(
            set(findings),
            key=lambda item: (
                item.field,
                item.start_char,
                item.end_char,
                item.category.value,
                item.code,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    """Content-addressed proof that specified matches were replaced."""

    artifact_id: str
    field: str
    original_sha256: str
    redacted_sha256: str
    finding_counts: tuple[tuple[str, int], ...]
    policy_digest: str
    schema_version: str = REDACTION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _require_text(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.field, str) or not _SAFE_FIELD_RE.fullmatch(self.field):
            raise ReleasePolicyError("redaction field is not a safe field identifier")
        for field_name in ("original_sha256", "redacted_sha256", "policy_digest"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        normalized: list[tuple[str, int]] = []
        if isinstance(self.finding_counts, (str, bytes, bytearray)):
            raise ReleasePolicyError("finding_counts must be a sequence")
        for item in self.finding_counts:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise ReleasePolicyError("finding_counts entries must be pairs")
            code, count = item
            code = _require_text(code, "finding code")
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 1
            ):
                raise ReleasePolicyError("redaction counts must be positive integers")
            normalized.append((code, count))
        if not normalized or len({code for code, _ in normalized}) != len(normalized):
            raise ReleasePolicyError("finding_counts must be non-empty and unique")
        object.__setattr__(self, "finding_counts", tuple(sorted(normalized)))
        if self.schema_version != REDACTION_RECEIPT_VERSION:
            raise ReleasePolicyError(
                f"unsupported redaction receipt version: {self.schema_version}"
            )

    @property
    def contains_secret_redaction(self) -> bool:
        return any(code.startswith("secret.") for code, _ in self.finding_counts)

    @property
    def receipt_id(self) -> str:
        return _canonical_digest(self.to_dict())

    def verifies(
        self,
        *,
        artifact_id: str,
        field: str,
        redacted_text: str,
        policy_digest: str,
    ) -> bool:
        return (
            self.artifact_id == artifact_id
            and self.field == field
            and self.redacted_sha256 == _sha256_text(redacted_text)
            and self.policy_digest == policy_digest
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "field": self.field,
            "finding_counts": [
                {"code": code, "count": count}
                for code, count in self.finding_counts
            ],
            "original_sha256": self.original_sha256,
            "policy_digest": self.policy_digest,
            "redacted_sha256": self.redacted_sha256,
            "schema_version": self.schema_version,
        }


def redact_release_text(
    *,
    artifact_id: str,
    field: str,
    text: str,
    policy_digest: str,
    max_chars: int = DEFAULT_MAX_SCAN_CHARS,
) -> tuple[str, RedactionReceipt | None]:
    """Redact detected secrets and personal data and return a safe receipt.

    Secret redaction is useful for containment, but the receipt deliberately
    preserves the fact that a secret was observed; admission therefore still
    rejects that source artifact.
    """

    artifact_id = _require_text(artifact_id, "artifact_id")
    policy_digest = _require_sha256(policy_digest, "policy_digest")
    findings = tuple(
        finding
        for finding in scan_release_text(field, text, max_chars=max_chars)
        if finding.category
        in {FindingCategory.SECRET, FindingCategory.PERSONAL_DATA}
    )
    if not findings:
        return text, None

    # Prefer the widest deterministic match at a start offset and discard
    # overlaps so matched material is never copied into a receipt.
    selected: list[ScanFinding] = []
    cursor = -1
    for finding in sorted(
        findings,
        key=lambda item: (item.start_char, -item.end_char, item.code),
    ):
        if finding.start_char < cursor:
            continue
        selected.append(finding)
        cursor = finding.end_char

    chunks: list[str] = []
    cursor = 0
    counts: dict[str, int] = {}
    for finding in selected:
        chunks.append(text[cursor : finding.start_char])
        chunks.append(f"[REDACTED:{finding.code}]")
        counts[finding.code] = counts.get(finding.code, 0) + 1
        cursor = finding.end_char
    chunks.append(text[cursor:])
    redacted = "".join(chunks)
    receipt = RedactionReceipt(
        artifact_id=artifact_id,
        field=field,
        original_sha256=_sha256_text(text),
        redacted_sha256=_sha256_text(redacted),
        finding_counts=tuple(counts.items()),
        policy_digest=policy_digest,
    )
    return redacted, receipt


@dataclass(frozen=True, slots=True)
class ReleaseBody:
    """One body or excerpt staged for release."""

    field: str
    text: str
    source_sha256: str
    is_full_body: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not _SAFE_FIELD_RE.fullmatch(self.field):
            raise ReleasePolicyError("body field is not a safe field identifier")
        if not isinstance(self.text, str):
            raise TypeError("body text must be a string")
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "source_sha256"),
        )
        if not isinstance(self.is_full_body, bool):
            raise ReleasePolicyError("is_full_body must be a boolean")

    @classmethod
    def from_source(
        cls, field: str, text: str, *, is_full_body: bool = False
    ) -> "ReleaseBody":
        if not isinstance(text, str):
            raise TypeError("body text must be a string")
        return cls(
            field=field,
            text=text,
            source_sha256=_sha256_text(text),
            is_full_body=is_full_body,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "is_full_body": self.is_full_body,
            "source_sha256": self.source_sha256,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """A local, non-authoritative candidate for publication."""

    artifact_id: str
    relative_path: str
    profile_id: str
    policy_digest: str
    source_revision: str
    license_provenance: LicenseProvenance
    bodies: tuple[ReleaseBody, ...] = ()
    redaction_receipts: tuple[RedactionReceipt, ...] = ()
    source_instruction_treatment: str = INERT_SOURCE_TREATMENT

    def __post_init__(self) -> None:
        for field_name in (
            "artifact_id",
            "relative_path",
            "profile_id",
            "source_revision",
            "source_instruction_treatment",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "policy_digest",
            _require_sha256(self.policy_digest, "policy_digest"),
        )
        if not isinstance(self.license_provenance, LicenseProvenance):
            raise TypeError("license_provenance must be LicenseProvenance")
        if any(not isinstance(body, ReleaseBody) for body in self.bodies):
            raise TypeError("bodies must contain only ReleaseBody values")
        if any(
            not isinstance(receipt, RedactionReceipt)
            for receipt in self.redaction_receipts
        ):
            raise TypeError(
                "redaction_receipts must contain only RedactionReceipt values"
            )
        bodies = tuple(sorted(self.bodies, key=lambda body: body.field))
        receipts = tuple(
            sorted(self.redaction_receipts, key=lambda receipt: receipt.field)
        )
        if len({body.field for body in bodies}) != len(bodies):
            raise ReleasePolicyError("body fields must be unique")
        if len({receipt.field for receipt in receipts}) != len(receipts):
            raise ReleasePolicyError("redaction receipt fields must be unique")
        if not {receipt.field for receipt in receipts}.issubset(
            {body.field for body in bodies}
        ):
            raise ReleasePolicyError("redaction receipts must reference a staged body")
        object.__setattr__(self, "bodies", bodies)
        object.__setattr__(self, "redaction_receipts", receipts)

    @property
    def candidate_digest(self) -> str:
        return _canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "bodies": [body.to_dict() for body in self.bodies],
            "license_provenance": self.license_provenance.to_dict(),
            "policy_digest": self.policy_digest,
            "profile_id": self.profile_id,
            "redaction_receipts": [
                receipt.to_dict() for receipt in self.redaction_receipts
            ],
            "relative_path": self.relative_path,
            "source_instruction_treatment": self.source_instruction_treatment,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class PublicationAdmission:
    """Bounded release decision; never an execution authorization."""

    artifact_id: str
    candidate_digest: str
    policy_digest: str
    profile_id: str
    decision: AdmissionDecision
    reason_codes: tuple[str, ...]
    findings: tuple[ScanFinding, ...]
    license_provenance: LicenseProvenance
    source_revision: str
    source_instruction_treatment: str = INERT_SOURCE_TREATMENT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _require_text(self.artifact_id, "artifact_id")
        )
        for field_name in ("candidate_digest", "policy_digest"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        try:
            object.__setattr__(self, "decision", AdmissionDecision(self.decision))
        except ValueError as exc:
            raise ReleasePolicyError("unsupported admission decision") from exc
        reasons = tuple(sorted(set(self.reason_codes)))
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise ReleasePolicyError("reason_codes must contain non-empty strings")
        if self.decision is AdmissionDecision.REJECT and not reasons:
            raise ReleasePolicyError("rejected admissions require a reason code")
        if self.decision is AdmissionDecision.ADMIT and any(
            finding.blocks_publication for finding in self.findings
        ):
            raise ReleasePolicyError("admitted publication has a blocking finding")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "findings",
            tuple(
                sorted(
                    set(self.findings),
                    key=lambda item: (
                        item.field,
                        item.start_char,
                        item.end_char,
                        item.code,
                    ),
                )
            ),
        )

    @property
    def admitted(self) -> bool:
        return self.decision is AdmissionDecision.ADMIT

    @property
    def authorizes_publication(self) -> bool:
        return self.admitted

    @property
    def grants_execution_authority(self) -> bool:
        return False

    @property
    def receipt_id(self) -> str:
        return _canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authorizes_publication": self.authorizes_publication,
            "candidate_digest": self.candidate_digest,
            "decision": self.decision.value,
            "findings": [finding.to_dict() for finding in self.findings],
            "grants_execution_authority": False,
            "license_provenance": self.license_provenance.to_dict(),
            "policy_digest": self.policy_digest,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "source_instruction_treatment": self.source_instruction_treatment,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesReleasePolicy:
    """Deterministic release scanner and publication admission gate."""

    profiles: tuple[BodyProfile, ...] = (
        DEFAULT_PUBLIC_PROFILE,
        DEFAULT_INTERNAL_PROFILE,
    )
    approved_license_expressions: tuple[str, ...] = DEFAULT_APPROVED_LICENSES
    max_scan_chars: int = DEFAULT_MAX_SCAN_CHARS
    schema_version: str = RELEASE_POLICY_VERSION
    _profile_map: Mapping[str, BodyProfile] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if any(not isinstance(profile, BodyProfile) for profile in self.profiles):
            raise TypeError("profiles must contain only BodyProfile values")
        profiles = tuple(sorted(self.profiles, key=lambda profile: profile.profile_id))
        if len({profile.profile_id for profile in profiles}) != len(profiles):
            raise ReleasePolicyError("profile identifiers must be unique")
        if PUBLIC_PROFILE_ID not in {profile.profile_id for profile in profiles}:
            raise ReleasePolicyError("the default public profile is required")
        licenses = tuple(
            sorted(
                {
                    _require_text(expression, "approved license expression")
                    for expression in self.approved_license_expressions
                },
                key=str.casefold,
            )
        )
        if not licenses:
            raise ReleasePolicyError("approved licenses must not be empty")
        if (
            isinstance(self.max_scan_chars, bool)
            or not isinstance(self.max_scan_chars, int)
            or self.max_scan_chars < 1
        ):
            raise ReleasePolicyError("max_scan_chars must be a positive integer")
        if self.schema_version != RELEASE_POLICY_VERSION:
            raise ReleasePolicyError(
                f"unsupported release policy version: {self.schema_version}"
            )
        object.__setattr__(self, "profiles", profiles)
        object.__setattr__(self, "approved_license_expressions", licenses)
        object.__setattr__(
            self,
            "_profile_map",
            MappingProxyType({profile.profile_id: profile for profile in profiles}),
        )

    @property
    def policy_digest(self) -> str:
        return _canonical_digest(self.to_dict())

    # Common shorter spelling for callers that bind policy identities.
    digest = policy_digest

    @property
    def public_profile(self) -> BodyProfile:
        return self._profile_map[PUBLIC_PROFILE_ID]

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_license_expressions": list(
                self.approved_license_expressions
            ),
            "inert_source_treatment": INERT_SOURCE_TREATMENT,
            "max_scan_chars": self.max_scan_chars,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "schema_version": self.schema_version,
        }

    def scan(self, field: str, text: str) -> tuple[ScanFinding, ...]:
        return scan_release_text(field, text, max_chars=self.max_scan_chars)

    def redact(
        self, *, artifact_id: str, field: str, text: str
    ) -> tuple[str, RedactionReceipt | None]:
        return redact_release_text(
            artifact_id=artifact_id,
            field=field,
            text=text,
            policy_digest=self.policy_digest,
            max_chars=self.max_scan_chars,
        )

    def evaluate(self, candidate: ReleaseCandidate) -> PublicationAdmission:
        """Evaluate a complete candidate against the current policy."""

        if not isinstance(candidate, ReleaseCandidate):
            raise TypeError("candidate must be a ReleaseCandidate")

        reasons: list[str] = []
        findings: list[ScanFinding] = []
        profile = self._profile_map.get(candidate.profile_id)

        if candidate.policy_digest != self.policy_digest:
            reasons.append("release.policy_drift")
        if profile is None:
            reasons.append("release.profile_unknown")
        if candidate.source_instruction_treatment != INERT_SOURCE_TREATMENT:
            reasons.append("release.source_treatment_drift")
        if not _is_safe_relative_release_path(candidate.relative_path):
            reasons.append("release.unsafe_path")

        license_provenance = candidate.license_provenance
        if not license_provenance.reviewed:
            reasons.append("release.license_unreviewed")
        approved = {
            _normalize_license_expression(expression)
            for expression in self.approved_license_expressions
        }
        if _normalize_license_expression(license_provenance.expression) not in approved:
            reasons.append("release.license_not_approved")
        if candidate.source_revision != license_provenance.source_revision:
            reasons.append("release.license_provenance_revision_mismatch")

        receipt_by_field = {
            receipt.field: receipt for receipt in candidate.redaction_receipts
        }
        if profile is not None:
            if profile.body_mode is BodyMode.OMIT and candidate.bodies:
                reasons.append("release.profile_omits_bodies")
            for body in candidate.bodies:
                if (
                    profile.audience is ReleaseAudience.PUBLIC
                    and body.is_full_body
                ):
                    reasons.append("release.public_full_body_forbidden")
                if (
                    profile.body_mode is BodyMode.BOUNDED_EXCERPTS
                    and len(body.text) > profile.max_excerpt_chars
                ):
                    reasons.append("release.public_excerpt_limit_exceeded")

                receipt = receipt_by_field.get(body.field)
                if receipt is not None:
                    if not receipt.verifies(
                        artifact_id=candidate.artifact_id,
                        field=body.field,
                        redacted_text=body.text,
                        policy_digest=self.policy_digest,
                    ) or body.source_sha256 != receipt.original_sha256:
                        reasons.append("release.redaction_receipt_invalid")
                    if receipt.contains_secret_redaction:
                        reasons.append("release.secret_detected")
                if _REDACTION_MARKER_RE.search(body.text) and receipt is None:
                    reasons.append("release.redaction_receipt_missing")

                body_findings = self.scan(body.field, body.text)
                findings.extend(body_findings)
                if any(
                    finding.category is FindingCategory.SECRET
                    for finding in body_findings
                ):
                    reasons.append("release.secret_detected")
                if any(
                    finding.category is FindingCategory.PERSONAL_DATA
                    for finding in body_findings
                ):
                    reasons.append("release.personal_data_detected")
                if any(
                    finding.category is FindingCategory.SCAN_BOUND
                    for finding in body_findings
                ):
                    reasons.append("release.scan_incomplete")

        findings_tuple = tuple(
            sorted(
                set(findings),
                key=lambda item: (
                    item.field,
                    item.start_char,
                    item.end_char,
                    item.code,
                ),
            )
        )
        # Prompt-injection strings are diagnostics, not instructions.  Their
        # presence does not execute anything and does not itself authorize or
        # block a clean, policy-conformant release.
        if any(
            finding.category is FindingCategory.PROMPT_INJECTION
            for finding in findings_tuple
        ):
            reasons.append("source.prompt_injection_retained_inert")

        blocking_reasons = [
            reason
            for reason in reasons
            if reason != "source.prompt_injection_retained_inert"
        ]
        decision = (
            AdmissionDecision.REJECT
            if blocking_reasons
            else AdmissionDecision.ADMIT
        )
        return PublicationAdmission(
            artifact_id=candidate.artifact_id,
            candidate_digest=candidate.candidate_digest,
            policy_digest=self.policy_digest,
            profile_id=candidate.profile_id,
            decision=decision,
            reason_codes=tuple(reasons),
            findings=findings_tuple,
            license_provenance=license_provenance,
            source_revision=candidate.source_revision,
            source_instruction_treatment=INERT_SOURCE_TREATMENT,
        )

    # Explicit admission-oriented spellings for release builders.
    admit = evaluate
    evaluate_publication = evaluate


def _is_safe_relative_release_path(value: str) -> bool:
    """Return whether ``value`` is a portable, confined POSIX release path."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or "\x00" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        return False
    path = PurePosixPath(value)
    parts = path.parts
    if path.is_absolute() or not parts:
        return False
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if any(part.casefold() in _FORBIDDEN_PATH_PARTS for part in parts):
        return False
    if any(part.startswith(".") for part in parts):
        return False
    return True


# Clear aliases for downstream builders that use publication terminology.
PublicationProfile = BodyProfile
PublicationCandidate = ReleaseCandidate
ReleaseAdmission = PublicationAdmission
ReleasePolicy = CVEfixesReleasePolicy


__all__ = [
    "AdmissionDecision",
    "BodyMode",
    "BodyProfile",
    "CVEfixesReleasePolicy",
    "DEFAULT_APPROVED_LICENSES",
    "DEFAULT_INTERNAL_PROFILE",
    "DEFAULT_MAX_SCAN_CHARS",
    "DEFAULT_PUBLIC_PROFILE",
    "FindingCategory",
    "INERT_SOURCE_TREATMENT",
    "INTERNAL_PROFILE_ID",
    "LicenseProvenance",
    "PUBLIC_PROFILE_ID",
    "PublicationAdmission",
    "PublicationCandidate",
    "PublicationProfile",
    "REDACTION_RECEIPT_VERSION",
    "RELEASE_POLICY_VERSION",
    "RedactionReceipt",
    "ReleaseAdmission",
    "ReleaseAudience",
    "ReleaseBody",
    "ReleaseCandidate",
    "ReleasePolicy",
    "ReleasePolicyError",
    "ScanFinding",
    "redact_release_text",
    "scan_release_text",
]
