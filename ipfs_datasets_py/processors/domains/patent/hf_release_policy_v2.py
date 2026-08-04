"""Public-release DLP, rights, and Dataset Viewer gates for patent HF v2.

PATLAW-158: fail-closed admission for JusticeDAO multi-repo Hub releases.

Public publication is refused **before credentials are resolved** when any of
the following hold:

* private, mixed, or unknown disclosure classifications
* missing or non-reviewed rights / privacy receipts
* secret, personal-data, or adversarial encoded leakage in bytes/metadata
* orphan index/graph joins or inconsistent count projections
* missing cards/configs, invalid Parquet, or stale mandatory sources
* Dataset Viewer is-valid/splits/rows/parquet/size/statistics contracts fail

This module never authenticates, uploads, or contacts the live Hub.  Offline
verification uses :class:`FakeDatasetViewerService` / :class:`FakeViewerGateway`.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Protocol

from .hf_layout_v2 import (
    BM25_REPOSITORY,
    COVERAGE_FILENAME,
    CORPUS_REPOSITORY,
    DATASET_CONFIGS_FILENAME,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    README_FILENAME,
    VECTORS_REPOSITORY,
)
from .hf_release_v2 import (
    POLICY_RECEIPT_FILENAME,
    QUALITY_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    REPOS_DIRNAME,
)
from .release_policy import (
    PRIVATE_CLASSIFICATIONS,
    PUBLIC_CLASSIFICATIONS,
    PatentReleasePolicy,
    PolicyFinding as V1PolicyFinding,
    RELEASE_POLICY_SHA256 as V1_POLICY_SHA256,
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
    is_private_classification,
    is_public_classification,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELEASE_POLICY_V2_VERSION: Final = "patent-legal-release-policy/v2"
MAX_SCAN_FIELD_CHARS: Final = 1_048_576
MAX_FINDINGS: Final = 256
MAX_ENCODED_DECODE_BYTES: Final = 65_536
MAX_VIEWER_RESPONSE_BYTES: Final = 2_097_152
DEFAULT_MAX_SOURCE_AGE_DAYS: Final = 400
PARQUET_MAGIC: Final = b"PAR1"

MANDATORY_SOURCE_IDS: Final[tuple[str, ...]] = (
    "govinfo/uscode",
    "govinfo/cfr",
    "uspto/public-pair",
)
CANONICAL_REPOSITORIES: Final[tuple[str, ...]] = (
    CORPUS_REPOSITORY,
    VECTORS_REPOSITORY,
    BM25_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
)
VIEWER_ENDPOINTS: Final[tuple[str, ...]] = (
    "is-valid",
    "splits",
    "rows",
    "parquet",
    "size",
    "statistics",
)

# Case-insensitive substrings that indicate private leakage even after decode.
# Full PEM armor is scanned via the v1 detector suite; these catch partial leaks.
_PRIVATE_LEAK_TOKENS: Final[tuple[str, ...]] = (
    "confidential_application",
    "privileged_work_product",
    "restricted_export_review",
    "credential_or_payment",
    'classification":"private',
    'classification": "private',
    'privacy_class":"private',
    'privacy_class": "private',
    "unpublished-application",
    "attorney-client privilege",
    "work product privilege",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN PRIVATE KEY",
)

_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Long base64 / urlsafe blobs that may hide secrets after decode.
_BASE64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/_-])(?:[A-Za-z0-9+/]{24,}={0,2}|[A-Za-z0-9_-]{24,}={0,2})"
    r"(?![A-Za-z0-9+/_-])"
)
_HEX_BLOB_RE = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{40,})(?![0-9a-fA-F])")
# Detects Hub token material in findings.detail (never retain matched secrets).
_HF_TOKEN_RE = re.compile(r"(?i)\bHF_TOKEN\b|\bhf_[A-Za-z0-9]{20,}\b")

_CREDENTIAL_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReleasePolicyV2Error(ValueError):
    """Raised when release-policy v2 input is malformed or unverifiable."""


class AdmissionRejectedError(ReleasePolicyV2Error):
    """Raised when public-release admission is refused fail-closed."""


class PrivacyRejectedError(AdmissionRejectedError):
    """Private, mixed, unknown, or secret-bearing material blocks admission."""


class RightsRejectedError(AdmissionRejectedError):
    """Missing or non-reviewed rights block admission."""


class OrphanRejectedError(AdmissionRejectedError):
    """Orphan index/graph joins block admission."""


class ParquetRejectedError(AdmissionRejectedError):
    """Invalid or unreadable Parquet shards block admission."""


class ViewerGateRejectedError(AdmissionRejectedError):
    """Dataset Viewer contract failures block admission."""


class StaleSourceRejectedError(AdmissionRejectedError):
    """Stale mandatory source disclosures block admission."""


class CountParityRejectedError(AdmissionRejectedError):
    """Inconsistent row counts across projections block admission."""


class CardConfigRejectedError(AdmissionRejectedError):
    """Missing cards or Viewer configs block admission."""


class CredentialPrematureError(ReleasePolicyV2Error):
    """Credentials must not be resolved before admission gates complete."""


# ---------------------------------------------------------------------------
# Findings / gates
# ---------------------------------------------------------------------------


class FindingCategory(str, Enum):
    SECRET = "secret"
    ENCODED_LEAKAGE = "encoded_leakage"
    PRIVATE_MARKER = "private_marker"
    PERSONAL_DATA = "personal_data"
    CLASSIFICATION = "classification"
    RIGHTS = "rights"
    LINEAGE = "lineage"
    ORPHAN = "orphan"
    PARQUET = "parquet"
    CARD_CONFIG = "card_config"
    COUNT_PARITY = "count_parity"
    STALE_SOURCE = "stale_source"
    VIEWER = "viewer"
    SCAN_LIMIT = "scan_limit"
    CREDENTIAL = "credential"


@dataclass(frozen=True, slots=True)
class PolicyFindingV2:
    """One bounded finding; never retains matched secret plaintext."""

    category: FindingCategory
    code: str
    field: str
    value_sha256: str
    start_char: int = 0
    end_char: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.category, FindingCategory):
            raise ReleasePolicyV2Error("category must be FindingCategory")
        code = str(self.code or "").strip()
        field = str(self.field or "").strip()
        if not code or not field:
            raise ReleasePolicyV2Error("finding code and field are required")
        digest = str(self.value_sha256 or "").strip().casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise ReleasePolicyV2Error("finding value_sha256 must be sha256 hex")
        if type(self.start_char) is not int or type(self.end_char) is not int:
            raise ReleasePolicyV2Error("finding offsets must be int")
        if self.start_char < 0 or self.end_char < self.start_char:
            raise ReleasePolicyV2Error("finding offsets are invalid")
        detail = str(self.detail or "")
        if "\x00" in detail or len(detail) > 512:
            raise ReleasePolicyV2Error(
                "finding detail must be short text without NUL"
            )
        if _HF_TOKEN_RE.search(detail):
            raise ReleasePolicyV2Error(
                "finding detail must not contain secret material"
            )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "value_sha256", digest)
        object.__setattr__(self, "detail", detail)

    @property
    def blocks_release(self) -> bool:
        return self.category is not FindingCategory.PERSONAL_DATA

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category.value,
            "code": self.code,
            "end_char": self.end_char,
            "field": self.field,
            "start_char": self.start_char,
            "value_sha256": self.value_sha256,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


_POLICY_V2_MANIFEST: Final[dict[str, Any]] = {
    "base_policy_sha256": V1_POLICY_SHA256,
    "default_max_source_age_days": DEFAULT_MAX_SOURCE_AGE_DAYS,
    "mandatory_source_ids": list(MANDATORY_SOURCE_IDS),
    "max_encoded_decode_bytes": MAX_ENCODED_DECODE_BYTES,
    "max_findings": MAX_FINDINGS,
    "max_scan_field_chars": MAX_SCAN_FIELD_CHARS,
    "private_classifications": sorted(PRIVATE_CLASSIFICATIONS),
    "public_classifications": sorted(PUBLIC_CLASSIFICATIONS),
    "repositories": list(CANONICAL_REPOSITORIES),
    "version": RELEASE_POLICY_V2_VERSION,
    "viewer_endpoints": list(VIEWER_ENDPOINTS),
}
RELEASE_POLICY_V2_SHA256: Final = hashlib.sha256(
    json.dumps(
        _POLICY_V2_MANIFEST,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class GateResult:
    """Result of one named admission gate."""

    name: str
    passed: bool
    reason_codes: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ReleasePolicyV2Error("gate name is required")
        codes = tuple(sorted(set(self.reason_codes)))
        if self.passed and codes:
            raise ReleasePolicyV2Error("passed gate cannot carry reason_codes")
        if not self.passed and not codes:
            raise ReleasePolicyV2Error("failed gate requires reason_codes")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "reason_codes", codes)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "details": dict(self.details),
            "name": self.name,
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class ReleaseAdmissionV2:
    """Fail-closed admission decision for a public v2 release candidate."""

    admitted: bool
    reason_codes: tuple[str, ...]
    findings: tuple[PolicyFindingV2, ...]
    gate_results: tuple[GateResult, ...]
    policy_sha256: str
    policy_version: str = RELEASE_POLICY_V2_VERSION
    credentials_resolved: bool = False
    inventory_summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.admitted != (not self.reason_codes):
            raise ReleasePolicyV2Error(
                "admitted must be false exactly when reason_codes are present"
            )
        codes = tuple(sorted(set(self.reason_codes)))
        if codes != tuple(self.reason_codes):
            object.__setattr__(self, "reason_codes", codes)
        digest = str(self.policy_sha256 or "").strip().casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise ReleasePolicyV2Error("policy_sha256 must be sha256 hex")
        if self.credentials_resolved:
            raise CredentialPrematureError(
                "credentials must not be resolved before admission gates complete"
            )
        object.__setattr__(self, "policy_sha256", digest)
        object.__setattr__(
            self, "inventory_summary", MappingProxyType(dict(self.inventory_summary))
        )

    def require_admitted(self) -> "ReleaseAdmissionV2":
        if not self.admitted:
            raise AdmissionRejectedError(
                "public release rejected before credentials: "
                + ", ".join(self.reason_codes)
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "credentials_resolved": self.credentials_resolved,
            "findings": [item.to_dict() for item in self.findings],
            "gate_results": [item.to_dict() for item in self.gate_results],
            "inventory_summary": dict(self.inventory_summary),
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class StagedParquetShard:
    """One staged Parquet shard with integrity and join metadata."""

    relative_path: str
    repository: str
    config_name: str
    sha256: str
    size_bytes: int
    row_count: int
    content: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "relative_path": self.relative_path,
            "repository": self.repository,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class RepositoryInventory:
    """Per-repository staged inventory for Viewer and integrity gates."""

    repository: str
    dataset_id: str
    role: str
    relative_paths: tuple[str, ...]
    parquet_shards: tuple[StagedParquetShard, ...]
    config_names: tuple[str, ...]
    config_row_counts: Mapping[str, int]
    has_readme: bool
    has_dataset_configs: bool
    has_coverage: bool
    coverage_sources: tuple[Mapping[str, Any], ...] = ()
    dataset_configs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "config_row_counts", MappingProxyType(dict(self.config_row_counts))
        )
        object.__setattr__(
            self, "dataset_configs", MappingProxyType(dict(self.dataset_configs))
        )

    @property
    def total_row_count(self) -> int:
        return sum(self.config_row_counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_names": list(self.config_names),
            "config_row_counts": dict(self.config_row_counts),
            "coverage_sources": [dict(s) for s in self.coverage_sources],
            "dataset_id": self.dataset_id,
            "has_coverage": self.has_coverage,
            "has_dataset_configs": self.has_dataset_configs,
            "has_readme": self.has_readme,
            "parquet_shards": [s.to_dict() for s in self.parquet_shards],
            "relative_paths": list(self.relative_paths),
            "repository": self.repository,
            "role": self.role,
            "total_row_count": self.total_row_count,
        }


@dataclass(frozen=True, slots=True)
class StagedReleaseInventory:
    """Full local release tree inventory used by admission gates."""

    root: str
    organization: str
    repositories: tuple[RepositoryInventory, ...]
    manifest: Mapping[str, Any]
    quality_report: Mapping[str, Any]
    policy_receipt: Mapping[str, Any]
    support_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))
        object.__setattr__(
            self, "quality_report", MappingProxyType(dict(self.quality_report))
        )
        object.__setattr__(
            self, "policy_receipt", MappingProxyType(dict(self.policy_receipt))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_keys": sorted(self.manifest),
            "organization": self.organization,
            "quality_orphan_check": self.quality_report.get("orphan_check"),
            "repositories": [r.to_dict() for r in self.repositories],
            "root": self.root,
            "support_paths": list(self.support_paths),
            "total_data_rows": self.quality_report.get("total_data_rows"),
        }


# ---------------------------------------------------------------------------
# Text / encoded scanners
# ---------------------------------------------------------------------------


def _iter_text_fields(value: Any, *, prefix: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    if isinstance(value, str):
        results.append((prefix, value))
    elif isinstance(value, bytes):
        try:
            results.append((prefix, value.decode("utf-8", errors="replace")))
        except UnicodeDecodeError:
            pass
    elif isinstance(value, Mapping):
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            results.extend(_iter_text_fields(value[key], prefix=child))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            results.extend(
                _iter_text_fields(item, prefix=f"{prefix}[{index}]")
            )
    return results


def _finding_sort_key(finding: PolicyFindingV2) -> tuple[Any, ...]:
    return (
        finding.category.value,
        finding.code,
        finding.field,
        finding.start_char,
        finding.end_char,
        finding.value_sha256,
        finding.detail,
    )


def _v1_to_v2_finding(finding: V1PolicyFinding) -> PolicyFindingV2:
    try:
        category = FindingCategory(finding.category.value)
    except ValueError:
        category = FindingCategory.SECRET
    return PolicyFindingV2(
        category=category,
        code=finding.code,
        field=finding.field,
        value_sha256=finding.value_sha256,
        start_char=finding.start_char,
        end_char=finding.end_char,
    )


def _try_b64_decode(candidate: str) -> bytes | None:
    text = candidate.strip()
    if len(text) < 24 or len(text) > MAX_ENCODED_DECODE_BYTES * 2:
        return None
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            pad = (-len(text)) % 4
            raw = decoder(text + ("=" * pad), validate=False)
        except (ValueError, TypeError):
            continue
        if len(raw) < 8 or len(raw) > MAX_ENCODED_DECODE_BYTES:
            continue
        return raw
    return None


def _try_hex_decode(candidate: str) -> bytes | None:
    text = candidate.strip()
    if len(text) < 40 or len(text) > MAX_ENCODED_DECODE_BYTES * 2:
        return None
    if len(text) % 2 != 0:
        return None
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return None
    if len(raw) < 8 or len(raw) > MAX_ENCODED_DECODE_BYTES:
        return None
    return raw


def _decoded_text(raw: bytes) -> str | None:
    for encoding in ("utf-8", "ascii", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t ")
        if max(len(text), 1) and (printable / max(len(text), 1)) >= 0.8:
            return text
    return None


def _private_marker_hits(text: str) -> list[str]:
    lowered = text.casefold()
    hits: list[str] = []
    for token in _PRIVATE_LEAK_TOKENS:
        if token.casefold() in lowered:
            hits.append(token)
    return hits


def _coerce_as_of(value: str | date | None) -> date:
    if value is None:
        return date(2026, 8, 1)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    return _parse_date(str(value))


def _parse_date(value: str) -> date:
    text = str(value or "").strip()
    if _DATE_RE.fullmatch(text):
        return date.fromisoformat(text)
    if _RFC3339_UTC_RE.fullmatch(text):
        return (
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .date()
        )
    raise ReleasePolicyV2Error(
        f"date must be YYYY-MM-DD or RFC3339 UTC, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Credentials (must remain unresolved during admission)
# ---------------------------------------------------------------------------


def credentials_are_resolved(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when Hub credential environment variables are present."""
    source = env if env is not None else os.environ
    for name in _CREDENTIAL_ENV_NAMES:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return True
    return False


def assert_credentials_unresolved(
    env: Mapping[str, str] | None = None,
) -> None:
    """Fail closed if credentials were resolved before admission gates."""
    if credentials_are_resolved(env):
        raise CredentialPrematureError(
            "Hub credentials are present in the environment; public-release "
            "DLP/rights/Viewer gates must complete before credentials are resolved"
        )


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class PatentHFReleasePolicyV2:
    """Side-effect-free DLP / rights / integrity gate for patent HF releases v2.

    Admission never requires Hub credentials.  Callers that resolve tokens
    before ``admit_*`` must fail via :func:`assert_credentials_unresolved`.
    """

    def __init__(
        self,
        *,
        max_field_chars: int = MAX_SCAN_FIELD_CHARS,
        max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
        as_of: str | date | None = None,
        base_policy: PatentReleasePolicy | None = None,
        mandatory_source_ids: Sequence[str] = MANDATORY_SOURCE_IDS,
    ) -> None:
        if (
            type(max_field_chars) is not int
            or max_field_chars <= 0
            or max_field_chars > MAX_SCAN_FIELD_CHARS
        ):
            raise ReleasePolicyV2Error(
                f"max_field_chars must be between 1 and {MAX_SCAN_FIELD_CHARS}"
            )
        if type(max_source_age_days) is not int or max_source_age_days <= 0:
            raise ReleasePolicyV2Error("max_source_age_days must be a positive int")
        self.max_field_chars = max_field_chars
        self.max_source_age_days = max_source_age_days
        self.as_of = _coerce_as_of(as_of)
        self.base_policy = base_policy or PatentReleasePolicy(
            max_field_chars=max_field_chars
        )
        ids = tuple(str(item).strip() for item in mandatory_source_ids if str(item).strip())
        if not ids:
            raise ReleasePolicyV2Error("mandatory_source_ids must be non-empty")
        self.mandatory_source_ids = ids

    @property
    def policy_sha256(self) -> str:
        return RELEASE_POLICY_V2_SHA256

    @property
    def policy_version(self) -> str:
        return RELEASE_POLICY_V2_VERSION

    def scan_text(self, field: str, value: str) -> tuple[PolicyFindingV2, ...]:
        findings: list[PolicyFindingV2] = []
        digest = _sha256_text(value)
        scan_value = value
        if len(value) > self.max_field_chars:
            findings.append(
                PolicyFindingV2(
                    category=FindingCategory.SCAN_LIMIT,
                    code="scan.field_limit_exceeded",
                    field=field,
                    value_sha256=digest,
                    start_char=self.max_field_chars,
                    end_char=len(value),
                )
            )
            scan_value = value[: self.max_field_chars]
        for v1 in self.base_policy.scan_payload(
            {"text": scan_value}, field_prefix=field
        ):
            findings.append(_v1_to_v2_finding(v1))
        for marker in _private_marker_hits(scan_value):
            findings.append(
                PolicyFindingV2(
                    category=FindingCategory.PRIVATE_MARKER,
                    code="content.private_marker",
                    field=field,
                    value_sha256=digest,
                    detail=f"marker={marker[:48]}",
                )
            )
        findings.extend(self._scan_encoded_candidates(field, scan_value, digest))
        return self._dedupe_findings(findings)

    def scan_payload(
        self,
        payload: Mapping[str, Any] | Any,
        *,
        field_prefix: str = "payload",
    ) -> tuple[PolicyFindingV2, ...]:
        findings: list[PolicyFindingV2] = []
        for field_name, text in _iter_text_fields(payload, prefix=field_prefix):
            findings.extend(self.scan_text(field_name, text))
            if len(findings) >= MAX_FINDINGS:
                findings = findings[:MAX_FINDINGS]
                findings.append(
                    PolicyFindingV2(
                        category=FindingCategory.SCAN_LIMIT,
                        code="scan.finding_limit_exceeded",
                        field=field_name,
                        value_sha256=_sha256_text(text),
                    )
                )
                break
        return self._dedupe_findings(findings)

    def scan_bytes(
        self,
        field: str,
        body: bytes,
        *,
        treat_as_text: bool = False,
    ) -> tuple[PolicyFindingV2, ...]:
        findings: list[PolicyFindingV2] = []
        digest = _sha256_bytes(body)
        if body.startswith(PARQUET_MAGIC):
            findings.extend(self._scan_parquet_bytes(field, body, digest))
            return self._dedupe_findings(findings)
        text = _decoded_text(body)
        if text is not None:
            findings.extend(self.scan_text(field, text))
        elif treat_as_text:
            ascii_view = body.decode("latin-1", errors="ignore")[
                : self.max_field_chars
            ]
            findings.extend(self.scan_text(field, ascii_view))
        return self._dedupe_findings(findings)

    def _scan_encoded_candidates(
        self, field: str, value: str, outer_digest: str
    ) -> list[PolicyFindingV2]:
        findings: list[PolicyFindingV2] = []
        candidates: list[tuple[str, str]] = []
        for match in _BASE64_CANDIDATE_RE.finditer(value):
            candidates.append(("base64", match.group(0)))
        for match in _HEX_BLOB_RE.finditer(value):
            candidates.append(("hex", match.group(0)))
        seen: set[str] = set()
        for encoding, candidate in candidates:
            key = f"{encoding}:{candidate[:32]}"
            if key in seen:
                continue
            seen.add(key)
            if encoding == "base64":
                raw = _try_b64_decode(candidate)
            else:
                raw = _try_hex_decode(candidate)
            if raw is None:
                continue
            text = _decoded_text(raw)
            if text is None:
                continue
            inner_digest = _sha256_text(text)
            for v1 in self.base_policy.scan_payload(
                {"decoded": text}, field_prefix=field
            ):
                if v1.category.value == "secret":
                    findings.append(
                        PolicyFindingV2(
                            category=FindingCategory.ENCODED_LEAKAGE,
                            code=f"encoded.{encoding}.secret",
                            field=field,
                            value_sha256=inner_digest,
                            detail=f"outer={outer_digest[:16]}",
                        )
                    )
            for marker in _private_marker_hits(text):
                findings.append(
                    PolicyFindingV2(
                        category=FindingCategory.ENCODED_LEAKAGE,
                        code=f"encoded.{encoding}.private_marker",
                        field=field,
                        value_sha256=inner_digest,
                        detail=f"marker={marker[:48]}",
                    )
                )
            if len(findings) >= MAX_FINDINGS:
                break
        return findings

    def _scan_parquet_bytes(
        self, field: str, body: bytes, digest: str
    ) -> list[PolicyFindingV2]:
        findings: list[PolicyFindingV2] = []
        try:
            import io

            import pyarrow.parquet as pq
        except ImportError:
            return findings
        try:
            table = pq.read_table(io.BytesIO(body))
        except Exception:
            findings.append(
                PolicyFindingV2(
                    category=FindingCategory.PARQUET,
                    code="parquet.unreadable",
                    field=field,
                    value_sha256=digest,
                )
            )
            return findings
        for column in table.column_names:
            col = table.column(column)
            for index, value in enumerate(col.to_pylist()):
                if isinstance(value, str):
                    findings.extend(
                        self.scan_text(f"{field}.{column}[{index}]", value)
                    )
                if len(findings) >= MAX_FINDINGS:
                    return findings
        return findings

    @staticmethod
    def _dedupe_findings(
        findings: Sequence[PolicyFindingV2],
    ) -> tuple[PolicyFindingV2, ...]:
        ordered = sorted(findings, key=_finding_sort_key)
        result: dict[tuple[Any, ...], PolicyFindingV2] = {}
        for item in ordered:
            result[_finding_sort_key(item)] = item
        out = tuple(result[key] for key in sorted(result))
        if len(out) > MAX_FINDINGS:
            return out[:MAX_FINDINGS]
        return out

    def evaluate_row_mapping(
        self, row: Mapping[str, Any], *, index: int = 0
    ) -> tuple[str, ...]:
        """Return reason codes for one release-row mapping (no staging)."""
        reasons: set[str] = set()
        classification = str(row.get("classification") or "").strip()
        if not classification:
            reasons.add("classification.missing")
        elif classification == "unknown":
            reasons.add("classification.unknown")
        elif classification in PRIVATE_CLASSIFICATIONS or is_private_classification(
            classification
        ):
            reasons.add("classification.private")
        elif not is_public_classification(classification):
            reasons.add("classification.not_public")

        rights_raw = row.get("rights_review")
        rights: RightsReview | None = None
        if isinstance(rights_raw, RightsReview):
            rights = rights_raw
        elif isinstance(rights_raw, Mapping):
            try:
                rights = RightsReview.from_dict(rights_raw)
            except Exception:
                reasons.add("rights.invalid")
        else:
            reasons.add("rights.invalid")
        if rights is not None:
            if not rights.reviewed_for_release:
                if rights.review_status is RightsReviewStatus.UNREVIEWED:
                    reasons.add("rights.unreviewed")
                elif rights.review_status is RightsReviewStatus.REJECTED:
                    reasons.add("rights.rejected")
                if not rights.redistribution_allowed:
                    reasons.add("rights.redistribution_not_allowed")
                reasons.add("rights.not_reviewed_for_release")

        privacy = row.get("privacy_review")
        if privacy is not None:
            try:
                if hasattr(privacy, "to_dict"):
                    privacy = privacy.to_dict()
                if not isinstance(privacy, Mapping):
                    raise TypeError("privacy_review mapping required")
                review_status = str(privacy.get("review_status") or "").strip()
                if review_status != "reviewed":
                    reasons.add("privacy.unreviewed")
                privacy_class = str(privacy.get("privacy_class") or "public").strip()
                if privacy_class != "public":
                    reasons.add("privacy.not_public")
            except Exception:
                reasons.add("privacy.invalid")

        payload: dict[str, Any] = {}
        fields = row.get("fields")
        if isinstance(fields, Mapping):
            payload["fields"] = dict(fields)
            for key in ("authoritative", "ai_derived"):
                nested = fields.get(key)
                if isinstance(nested, Mapping):
                    payload[key] = dict(nested)
        if isinstance(row.get("payload"), Mapping):
            payload["payload"] = dict(row["payload"])  # type: ignore[index]
        for key in ("record_id", "config_name", "text", "notes"):
            if key in row and row[key] is not None:
                payload[key] = row[key]

        findings = self.scan_payload(payload, field_prefix=f"row[{index}]")
        for finding in findings:
            if finding.category in (
                FindingCategory.SECRET,
                FindingCategory.ENCODED_LEAKAGE,
            ):
                reasons.add("content.secret_or_encoded_leakage")
            elif finding.category is FindingCategory.PRIVATE_MARKER:
                reasons.add("content.private_marker")
            elif finding.category is FindingCategory.SCAN_LIMIT:
                reasons.add("scan.incomplete")
        return tuple(sorted(reasons))

    def evaluate_rows(
        self, rows: Sequence[Mapping[str, Any] | Any]
    ) -> ReleaseAdmissionV2:
        """Admit a pure-public row batch or reject before staging."""
        assert_credentials_unresolved()
        if not isinstance(rows, Sequence) or isinstance(
            rows, (str, bytes, bytearray)
        ):
            raise ReleasePolicyV2Error("rows must be a sequence")
        if len(rows) == 0:
            return self._reject(
                reason_codes=("batch.empty",),
                findings=(),
                gates=(
                    GateResult(
                        name="rows", passed=False, reason_codes=("batch.empty",)
                    ),
                ),
            )

        batch_reasons: set[str] = set()
        findings: list[PolicyFindingV2] = []
        classes: set[str] = set()
        for index, raw in enumerate(rows):
            mapping: Mapping[str, Any]
            if hasattr(raw, "to_dict") and callable(raw.to_dict):
                mapping = raw.to_dict()
            elif isinstance(raw, Mapping):
                mapping = dict(raw)
            else:
                batch_reasons.add("batch.invalid_row")
                continue
            row_reasons = self.evaluate_row_mapping(mapping, index=index)
            batch_reasons.update(row_reasons)
            classification = str(mapping.get("classification") or "").strip() or "unknown"
            classes.add(classification)
            payload: dict[str, Any] = {}
            fields = mapping.get("fields")
            if isinstance(fields, Mapping):
                payload["fields"] = dict(fields)
                for key in ("authoritative", "ai_derived"):
                    nested = fields.get(key)
                    if isinstance(nested, Mapping):
                        payload[key] = dict(nested)
            if isinstance(mapping.get("payload"), Mapping):
                payload["payload"] = dict(mapping["payload"])  # type: ignore[index]
            findings.extend(
                self.scan_payload(payload, field_prefix=f"row[{index}]")
            )

        has_public = bool(classes & PUBLIC_CLASSIFICATIONS)
        has_private = bool(classes & PRIVATE_CLASSIFICATIONS)
        has_unknown = "unknown" in classes
        if has_private and has_public:
            batch_reasons.add("batch.mixed_private_public")
        if has_private:
            batch_reasons.add("batch.private_input")
        if has_unknown:
            batch_reasons.add("batch.unknown_classification")
        if has_private or has_unknown:
            batch_reasons.add("privacy.rejected_before_staging")

        ordered_findings = self._dedupe_findings(findings)
        passed = not batch_reasons
        gate = GateResult(
            name="rows",
            passed=passed,
            reason_codes=tuple(sorted(batch_reasons)),
            details={
                "row_count": len(rows),
                "classifications": sorted(classes),
            },
        )
        return ReleaseAdmissionV2(
            admitted=passed,
            reason_codes=tuple(sorted(batch_reasons)),
            findings=ordered_findings,
            gate_results=(gate,),
            policy_sha256=self.policy_sha256,
            inventory_summary={"row_count": len(rows)},
        )

    def evaluate_staged_tree(
        self,
        root: str | Path,
        *,
        viewer_gateway: ViewerGateway | None = None,
        run_viewer_gate: bool = True,
    ) -> ReleaseAdmissionV2:
        """Evaluate a staged multi-repo release tree (local, credential-free)."""
        assert_credentials_unresolved()
        inventory = load_staged_release_inventory(root)
        return self.evaluate_inventory(
            inventory,
            viewer_gateway=viewer_gateway,
            run_viewer_gate=run_viewer_gate,
        )

    def evaluate_inventory(
        self,
        inventory: StagedReleaseInventory,
        *,
        viewer_gateway: ViewerGateway | None = None,
        run_viewer_gate: bool = True,
    ) -> ReleaseAdmissionV2:
        """Run all local + Viewer gates against a release inventory."""
        assert_credentials_unresolved()
        reasons: set[str] = set()
        findings: list[PolicyFindingV2] = []
        gates: list[GateResult] = []

        card_gate = self._gate_cards_configs(inventory)
        gates.append(card_gate)
        reasons.update(card_gate.reason_codes)

        parquet_gate, parquet_findings = self._gate_parquet(inventory)
        gates.append(parquet_gate)
        reasons.update(parquet_gate.reason_codes)
        findings.extend(parquet_findings)

        rights_gate, rights_findings = self._gate_rights_and_dlp(inventory)
        gates.append(rights_gate)
        reasons.update(rights_gate.reason_codes)
        findings.extend(rights_findings)

        orphan_gate = self._gate_orphans(inventory)
        gates.append(orphan_gate)
        reasons.update(orphan_gate.reason_codes)

        count_gate = self._gate_count_parity(inventory)
        gates.append(count_gate)
        reasons.update(count_gate.reason_codes)

        stale_gate = self._gate_stale_sources(inventory)
        gates.append(stale_gate)
        reasons.update(stale_gate.reason_codes)

        if run_viewer_gate:
            gateway = viewer_gateway or FakeViewerGateway.from_inventory(inventory)
            viewer_gate = DatasetViewerGate().verify(inventory, gateway)
            gates.append(viewer_gate)
            reasons.update(viewer_gate.reason_codes)

        ordered_findings = self._dedupe_findings(findings)
        admitted = not reasons
        return ReleaseAdmissionV2(
            admitted=admitted,
            reason_codes=tuple(sorted(reasons)),
            findings=ordered_findings,
            gate_results=tuple(gates),
            policy_sha256=self.policy_sha256,
            inventory_summary=inventory.to_dict(),
        )

    def admit_public_release(
        self,
        *,
        rows: Sequence[Mapping[str, Any] | Any] | None = None,
        staged_root: str | Path | None = None,
        inventory: StagedReleaseInventory | None = None,
        viewer_gateway: ViewerGateway | None = None,
        run_viewer_gate: bool = True,
    ) -> ReleaseAdmissionV2:
        """Master entry: admit rows and/or a staged tree before credentials."""
        assert_credentials_unresolved()
        if rows is None and staged_root is None and inventory is None:
            raise ReleasePolicyV2Error(
                "admit_public_release requires rows, staged_root, or inventory"
            )
        results: list[ReleaseAdmissionV2] = []
        if rows is not None:
            results.append(self.evaluate_rows(rows))
        if inventory is not None:
            results.append(
                self.evaluate_inventory(
                    inventory,
                    viewer_gateway=viewer_gateway,
                    run_viewer_gate=run_viewer_gate,
                )
            )
        elif staged_root is not None:
            results.append(
                self.evaluate_staged_tree(
                    staged_root,
                    viewer_gateway=viewer_gateway,
                    run_viewer_gate=run_viewer_gate,
                )
            )
        reasons: set[str] = set()
        findings: list[PolicyFindingV2] = []
        gates: list[GateResult] = []
        summary: dict[str, Any] = {}
        for item in results:
            reasons.update(item.reason_codes)
            findings.extend(item.findings)
            gates.extend(item.gate_results)
            summary.update(dict(item.inventory_summary))
        return ReleaseAdmissionV2(
            admitted=not reasons,
            reason_codes=tuple(sorted(reasons)),
            findings=self._dedupe_findings(findings),
            gate_results=tuple(gates),
            policy_sha256=self.policy_sha256,
            inventory_summary=summary,
        )

    def _gate_cards_configs(
        self, inventory: StagedReleaseInventory
    ) -> GateResult:
        reasons: set[str] = set()
        missing: list[str] = []
        if not inventory.repositories:
            reasons.add("inventory.no_repositories")
        for repo in inventory.repositories:
            if not repo.has_readme:
                reasons.add("card.missing_readme")
                missing.append(f"{repo.repository}/{README_FILENAME}")
            if not repo.has_dataset_configs:
                reasons.add("config.missing_dataset_configs")
                missing.append(f"{repo.repository}/{DATASET_CONFIGS_FILENAME}")
            if not repo.has_coverage:
                reasons.add("card.missing_coverage")
                missing.append(f"{repo.repository}/{COVERAGE_FILENAME}")
            if repo.parquet_shards and not repo.config_names:
                reasons.add("config.empty_with_parquet")
            for name in repo.config_names:
                lowered = name.casefold()
                for token in (
                    "private",
                    "confidential",
                    "privileged",
                    "secret",
                    "mixed",
                    "unknown",
                ):
                    if token in lowered:
                        reasons.add("config.private_name")
                        break
        support_required = (
            RELEASE_MANIFEST_FILENAME,
            QUALITY_REPORT_FILENAME,
            POLICY_RECEIPT_FILENAME,
        )
        missing_support = [
            name for name in support_required if name not in inventory.support_paths
        ]
        if missing_support:
            reasons.add("support.missing_required")
            missing.extend(missing_support)
        return GateResult(
            name="cards_configs",
            passed=not reasons,
            reason_codes=tuple(sorted(reasons)),
            details={"missing": sorted(set(missing))},
        )

    def _gate_parquet(
        self, inventory: StagedReleaseInventory
    ) -> tuple[GateResult, list[PolicyFindingV2]]:
        reasons: set[str] = set()
        findings: list[PolicyFindingV2] = []
        invalid: list[str] = []
        for repo in inventory.repositories:
            for shard in repo.parquet_shards:
                body = shard.content
                if not body and shard.size_bytes > 0:
                    # content optional for pure metadata inventories
                    continue
                if not body:
                    reasons.add("parquet.content_unavailable")
                    invalid.append(shard.relative_path)
                    continue
                if not body.startswith(PARQUET_MAGIC) or not body.endswith(
                    PARQUET_MAGIC
                ):
                    # Strict magic check: parquet files start with PAR1; footer
                    # also ends with PAR1. Accept start-only if body is short.
                    if not body.startswith(PARQUET_MAGIC):
                        reasons.add("parquet.invalid_magic")
                        findings.append(
                            PolicyFindingV2(
                                category=FindingCategory.PARQUET,
                                code="parquet.invalid_magic",
                                field=shard.relative_path,
                                value_sha256=_sha256_bytes(body)
                                if body
                                else "0" * 64,
                            )
                        )
                        invalid.append(shard.relative_path)
                        continue
                if (
                    _SHA256_RE.fullmatch(shard.sha256)
                    and _sha256_bytes(body) != shard.sha256
                ):
                    # Integrity drift — treat as unreadable for admission.
                    reasons.add("parquet.unreadable")
                    invalid.append(shard.relative_path)
                try:
                    import io

                    import pyarrow.parquet as pq

                    pf = pq.ParquetFile(io.BytesIO(body))
                    rows = int(pf.metadata.num_rows)
                    if shard.row_count >= 0 and rows != shard.row_count:
                        reasons.add("parquet.row_count_mismatch")
                        invalid.append(shard.relative_path)
                    if rows == 0:
                        reasons.add("parquet.empty_shard")
                        invalid.append(shard.relative_path)
                except Exception:
                    reasons.add("parquet.unreadable")
                    findings.append(
                        PolicyFindingV2(
                            category=FindingCategory.PARQUET,
                            code="parquet.unreadable",
                            field=shard.relative_path,
                            value_sha256=_sha256_bytes(body),
                        )
                    )
                    invalid.append(shard.relative_path)
                    continue
                findings.extend(
                    self.scan_bytes(
                        shard.relative_path, body, treat_as_text=False
                    )
                )
        return (
            GateResult(
                name="parquet",
                passed=not reasons,
                reason_codes=tuple(sorted(reasons)),
                details={"invalid": sorted(set(invalid))},
            ),
            findings,
        )

    def _gate_rights_and_dlp(
        self, inventory: StagedReleaseInventory
    ) -> tuple[GateResult, list[PolicyFindingV2]]:
        reasons: set[str] = set()
        findings: list[PolicyFindingV2] = []
        receipt = dict(inventory.policy_receipt) if inventory.policy_receipt else {}
        if receipt:
            if receipt.get("admitted") is not True:
                reasons.add("policy.receipt_not_admitted")
            findings.extend(
                self.scan_payload(receipt, field_prefix="policy_receipt")
            )
        else:
            reasons.add("policy.receipt_missing")

        for label, payload in (
            ("manifest", dict(inventory.manifest)),
            ("quality_report", dict(inventory.quality_report)),
        ):
            findings.extend(self.scan_payload(payload, field_prefix=label))

        for repo in inventory.repositories:
            for source in repo.coverage_sources:
                license_expression = str(
                    source.get("license_expression") or ""
                ).strip()
                if not license_expression:
                    reasons.add("rights.missing_license")
                findings.extend(
                    self.scan_payload(
                        dict(source),
                        field_prefix=f"{repo.repository}.coverage",
                    )
                )
            if repo.dataset_configs:
                findings.extend(
                    self.scan_payload(
                        dict(repo.dataset_configs),
                        field_prefix=f"{repo.repository}.dataset_configs",
                    )
                )

        for finding in findings:
            if finding.category in (
                FindingCategory.SECRET,
                FindingCategory.ENCODED_LEAKAGE,
            ):
                reasons.add("content.secret_or_encoded_leakage")
            elif finding.category is FindingCategory.PRIVATE_MARKER:
                reasons.add("content.private_marker")
            elif finding.category is FindingCategory.CLASSIFICATION:
                reasons.add("classification.blocked")

        summary = inventory.policy_receipt.get("classification_summary")
        if isinstance(summary, Mapping):
            classes = {str(k) for k in summary}
            if classes & PRIVATE_CLASSIFICATIONS:
                reasons.add("batch.private_input")
            if "unknown" in classes:
                reasons.add("batch.unknown_classification")
            if (classes & PRIVATE_CLASSIFICATIONS) and (
                classes & PUBLIC_CLASSIFICATIONS
            ):
                reasons.add("batch.mixed_private_public")

        return (
            GateResult(
                name="rights_dlp",
                passed=not reasons,
                reason_codes=tuple(sorted(reasons)),
            ),
            findings,
        )

    def _gate_orphans(self, inventory: StagedReleaseInventory) -> GateResult:
        reasons: set[str] = set()
        quality = inventory.quality_report
        orphan_joins = quality.get("orphan_joins")
        try:
            if orphan_joins is not None and int(orphan_joins) > 0:
                reasons.add("orphan.quality_report")
        except (TypeError, ValueError):
            reasons.add("orphan.quality_report")
        orphan_check = quality.get("orphan_check")
        if orphan_check is False:
            reasons.add("orphan.check_failed")
        elif orphan_check is None and inventory.quality_report:
            # quality present but orphan_check missing
            if "orphan_check" not in quality and "orphan_joins" not in quality:
                reasons.add("orphan.check_missing")
        structural = _structural_orphan_probe(inventory)
        if structural:
            reasons.add("orphan.structural_join")
        return GateResult(
            name="orphans",
            passed=not reasons,
            reason_codes=tuple(sorted(reasons)),
            details={"structural_orphans": structural},
        )

    def _gate_count_parity(
        self, inventory: StagedReleaseInventory
    ) -> GateResult:
        reasons: set[str] = set()
        mismatches: list[str] = []
        manifest = inventory.manifest
        quality = inventory.quality_report
        manifest_counts = manifest.get("config_row_counts")
        quality_counts = quality.get("config_row_counts")
        if manifest_counts is not None and not isinstance(manifest_counts, Mapping):
            reasons.add("count.manifest_invalid")
            manifest_counts = None
        if quality_counts is not None and not isinstance(quality_counts, Mapping):
            reasons.add("count.quality_invalid")
            quality_counts = None

        inventory_counts: dict[str, int] = {}
        for repo in inventory.repositories:
            for name, count in repo.config_row_counts.items():
                try:
                    inventory_counts[name] = inventory_counts.get(name, 0) + int(
                        count
                    )
                except (TypeError, ValueError):
                    reasons.add("count.inventory_mismatch")

        if isinstance(manifest_counts, Mapping) and isinstance(
            quality_counts, Mapping
        ):
            shared = set(manifest_counts) | set(quality_counts)
            for name in shared:
                try:
                    m = int(manifest_counts.get(name, 0))  # type: ignore[arg-type]
                    q = int(quality_counts.get(name, 0))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    reasons.add("count.manifest_quality_mismatch")
                    continue
                if m != q:
                    reasons.add("count.manifest_quality_mismatch")
                    mismatches.append(f"{name}:manifest!=quality")
                inv = inventory_counts.get(name)
                if inv is not None and inv != m:
                    reasons.add("count.inventory_mismatch")
                    mismatches.append(f"{name}:manifest!=inventory")
        elif inventory_counts and isinstance(manifest_counts, Mapping):
            for name, count in inventory_counts.items():
                try:
                    m = int(manifest_counts.get(name, -1))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    reasons.add("count.manifest_invalid")
                    continue
                if m != count:
                    reasons.add("count.inventory_mismatch")
                    mismatches.append(f"{name}:manifest!=inventory")

        total_manifest = manifest.get("total_data_rows")
        total_quality = quality.get("total_data_rows")
        try:
            if total_manifest is not None and total_quality is not None:
                if int(total_manifest) != int(total_quality):
                    reasons.add("count.total_mismatch")
                    mismatches.append("total_manifest!=total_quality")
        except (TypeError, ValueError):
            reasons.add("count.total_invalid")

        repo_entries = manifest.get("repositories")
        if isinstance(repo_entries, Sequence) and not isinstance(
            repo_entries, (str, bytes, bytearray)
        ):
            for entry in repo_entries:
                if not isinstance(entry, Mapping):
                    continue
                name = str(entry.get("repository") or "")
                declared = entry.get("total_row_count")
                for repo in inventory.repositories:
                    if repo.repository == name:
                        try:
                            if declared is not None and int(declared) != int(
                                repo.total_row_count
                            ):
                                reasons.add("count.repo_total_mismatch")
                                mismatches.append(name)
                        except (TypeError, ValueError):
                            reasons.add("count.repo_total_invalid")

        return GateResult(
            name="count_parity",
            passed=not reasons,
            reason_codes=tuple(sorted(reasons)),
            details={
                "mismatches": mismatches,
                "inventory_counts": inventory_counts,
            },
        )

    def _gate_stale_sources(
        self, inventory: StagedReleaseInventory
    ) -> GateResult:
        reasons: set[str] = set()
        stale: list[str] = []
        missing: list[str] = []
        seen: set[str] = set()
        as_of = self.as_of
        for repo in inventory.repositories:
            for source in repo.coverage_sources:
                source_id = str(source.get("source_id") or "").strip()
                if not source_id:
                    continue
                seen.add(source_id)
                current = str(
                    source.get("current_through")
                    or source.get("official_edition_cutoff")
                    or ""
                ).strip()
                if not current:
                    reasons.add("source.missing_current_through")
                    missing.append(source_id)
                    continue
                try:
                    current_date = _parse_date(current)
                except ReleasePolicyV2Error:
                    reasons.add("source.invalid_current_through")
                    missing.append(source_id)
                    continue
                age_days = (as_of - current_date).days
                if age_days < 0:
                    reasons.add("source.future_current_through")
                    stale.append(source_id)
                elif (
                    source_id in self.mandatory_source_ids
                    and age_days > self.max_source_age_days
                ):
                    reasons.add("source.stale_mandatory")
                    stale.append(source_id)
        for required in self.mandatory_source_ids:
            if required not in seen:
                # mandatory may appear on any repo coverage; require presence
                # only when some coverage is present
                if any(repo.coverage_sources for repo in inventory.repositories):
                    reasons.add("source.mandatory_missing")
                    missing.append(required)
        return GateResult(
            name="stale_sources",
            passed=not reasons,
            reason_codes=tuple(sorted(reasons)),
            details={
                "as_of": as_of.isoformat(),
                "max_source_age_days": self.max_source_age_days,
                "missing": sorted(set(missing)),
                "stale": sorted(set(stale)),
            },
        )

    def _reject(
        self,
        *,
        reason_codes: Sequence[str],
        findings: Sequence[PolicyFindingV2],
        gates: Sequence[GateResult],
        inventory_summary: Mapping[str, Any] | None = None,
    ) -> ReleaseAdmissionV2:
        codes = tuple(sorted(set(reason_codes)))
        return ReleaseAdmissionV2(
            admitted=False,
            reason_codes=codes,
            findings=self._dedupe_findings(findings),
            gate_results=tuple(gates),
            policy_sha256=self.policy_sha256,
            inventory_summary=dict(inventory_summary or {}),
        )


DEFAULT_RELEASE_POLICY_V2: Final = PatentHFReleasePolicyV2()


# ---------------------------------------------------------------------------
# Viewer gateway (offline)
# ---------------------------------------------------------------------------


class ViewerGateway(Protocol):
    """Minimal protocol for Dataset Viewer endpoint access."""

    def viewer(
        self, endpoint: str, params: Mapping[str, str], *, token: str | None = None
    ) -> Mapping[str, Any]:
        ...


@dataclass
class FakeDatasetViewerService:
    """Offline Dataset Viewer stand-in driven by a staged inventory.

    A successful HTTP-shaped payload is **not** sufficient for admission: the
    :class:`DatasetViewerGate` still validates split inventory, parquet
    bindings, row features, size, and statistics against the local inventory.
    """

    inventory: StagedReleaseInventory
    force_invalid: bool = False
    drop_endpoints: frozenset[str] = field(default_factory=frozenset)
    corrupt_splits: bool = False
    corrupt_parquet: bool = False
    corrupt_rows: bool = False
    corrupt_size: bool = False
    corrupt_statistics: bool = False
    calls: list[tuple[str, Mapping[str, str]]] = field(default_factory=list)

    def response(
        self, endpoint: str, params: Mapping[str, str]
    ) -> Mapping[str, Any]:
        self.calls.append((endpoint, dict(params)))
        if endpoint not in VIEWER_ENDPOINTS:
            raise ViewerGateRejectedError(f"unsupported Viewer endpoint: {endpoint}")
        if endpoint in self.drop_endpoints:
            raise ViewerGateRejectedError(
                f"Viewer endpoint unavailable: {endpoint}"
            )
        dataset = str(params.get("dataset") or "").strip()
        repo = self._repo_for_dataset(dataset)

        if endpoint == "is-valid":
            if self.force_invalid:
                return {"viewer": False, "preview": False, "partial": False}
            return {"viewer": True, "preview": True}

        if endpoint == "splits":
            if self.corrupt_splits:
                return {"splits": [{"config": "bogus", "split": "train"}]}
            splits = [
                {"dataset": dataset, "config": name, "split": "train"}
                for name in repo.config_names
            ]
            return {"splits": splits}

        if endpoint == "parquet":
            if self.corrupt_parquet:
                return {
                    "parquet_files": [
                        {
                            "dataset": dataset,
                            "config": "bogus",
                            "split": "train",
                            "url": "https://example.invalid/x.parquet",
                            "filename": "x.parquet",
                            "size": 1,
                        }
                    ]
                }
            files = []
            for shard in repo.parquet_shards:
                config = shard.config_name
                files.append(
                    {
                        "dataset": dataset,
                        "config": config,
                        "split": "train",
                        "url": (
                            f"https://huggingface.co/datasets/{dataset}"
                            f"/resolve/main/{shard.relative_path}"
                        ),
                        "filename": PurePosixPath(shard.relative_path).name,
                        "size": shard.size_bytes,
                    }
                )
            return {"parquet_files": files}

        if endpoint == "rows":
            config = str(params.get("config") or "").strip()
            split = str(params.get("split") or "train").strip()
            if self.corrupt_rows:
                return {
                    "dataset": dataset,
                    "config": config,
                    "split": split,
                    "features": [],
                    "rows": [],
                }
            features = [
                {"feature_idx": index, "name": name, "type": {"dtype": "string"}}
                for index, name in enumerate(_features_for_config(repo, config))
            ]
            num_rows = int(repo.config_row_counts.get(config, 0))
            sample_rows = [
                {
                    "row_idx": index,
                    "row": {"sample": f"sample-{index}"},
                    "truncated_cells": [],
                }
                for index in range(min(num_rows, 1))
            ]
            return {
                "dataset": dataset,
                "config": config,
                "split": split,
                "features": features,
                "rows": sample_rows,
                "num_rows_total": num_rows,
                "num_rows_per_page": 100,
            }

        if endpoint == "size":
            if self.corrupt_size:
                return {"dataset": dataset, "configs": []}
            configs = {
                name: {
                    "num_bytes": sum(
                        s.size_bytes
                        for s in repo.parquet_shards
                        if s.config_name == name
                    ),
                    "num_rows": int(count),
                }
                for name, count in repo.config_row_counts.items()
            }
            return {
                "dataset": dataset,
                "configs": configs,
                "num_rows": int(repo.total_row_count),
            }

        if endpoint == "statistics":
            if self.corrupt_statistics:
                return {"dataset": dataset, "statistics": []}
            # Emit one statistics entry per declared config (including zero-row
            # configs) so Viewer contracts match dataset_configs inventory.
            names = repo.config_names or tuple(sorted(repo.config_row_counts))
            stats = [
                {
                    "dataset": dataset,
                    "config": name,
                    "split": "train",
                    "num_examples": int(repo.config_row_counts.get(name, 0)),
                    "statistics": {},
                }
                for name in names
            ]
            return {"dataset": dataset, "statistics": stats}

        raise ViewerGateRejectedError(f"unhandled Viewer endpoint: {endpoint}")

    def _repo_for_dataset(self, dataset_id: str) -> RepositoryInventory:
        for repository in self.inventory.repositories:
            if repository.dataset_id == dataset_id or dataset_id.endswith(
                repository.repository
            ):
                return repository
        raise ViewerGateRejectedError(
            f"unknown dataset for Viewer service: {dataset_id}"
        )


class FakeViewerGateway:
    """ViewerGateway that never leaves process memory and never uses tokens."""

    def __init__(self, service: FakeDatasetViewerService) -> None:
        self.service = service
        self.token_seen = False

    @classmethod
    def from_inventory(cls, inventory: StagedReleaseInventory) -> "FakeViewerGateway":
        return cls(FakeDatasetViewerService(inventory=inventory))

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        *,
        token: str | None = None,
    ) -> Mapping[str, Any]:
        if token:
            self.token_seen = True
            raise CredentialPrematureError(
                "Viewer gateway received a credential during local admission"
            )
        return self.service.response(endpoint, params)


class DatasetViewerGate:
    """Validate Hub Dataset Viewer response contracts against local inventory.

    A bare ``viewer: true`` HTTP response is **not** sufficient.  Every
    endpoint in :data:`VIEWER_ENDPOINTS` must agree with the staged release.
    """

    def verify(
        self,
        inventory: StagedReleaseInventory,
        gateway: ViewerGateway,
    ) -> GateResult:
        reasons: set[str] = set()
        details: dict[str, Any] = {"repositories": []}
        for repo in inventory.repositories:
            repo_detail: dict[str, Any] = {"dataset_id": repo.dataset_id}
            dataset = repo.dataset_id
            try:
                validity = gateway.viewer("is-valid", {"dataset": dataset})
            except CredentialPrematureError:
                raise
            except Exception as exc:
                reasons.add("viewer.is_valid_unavailable")
                repo_detail["error"] = type(exc).__name__
                details["repositories"].append(repo_detail)
                continue
            if not (
                isinstance(validity, Mapping)
                and validity.get("viewer") is True
            ):
                reasons.add("viewer.not_valid")

            try:
                splits_response = gateway.viewer("splits", {"dataset": dataset})
            except CredentialPrematureError:
                raise
            except Exception:
                reasons.add("viewer.splits_unavailable")
                details["repositories"].append(repo_detail)
                continue
            raw_splits = splits_response.get("splits") if isinstance(
                splits_response, Mapping
            ) else None
            if not isinstance(raw_splits, list):
                reasons.add("viewer.splits_malformed")
            else:
                actual = sorted(
                    {
                        str(item.get("config") or "")
                        for item in raw_splits
                        if isinstance(item, Mapping)
                    }
                )
                expected = sorted(repo.config_names)
                if actual != expected:
                    # empty config repos (index-only placeholders) may have no
                    # configs — still require exact match of declared names
                    reasons.add("viewer.splits_mismatch")
                    repo_detail["splits_actual"] = actual
                    repo_detail["splits_expected"] = expected

            try:
                parquet_response = gateway.viewer(
                    "parquet", {"dataset": dataset}
                )
            except CredentialPrematureError:
                raise
            except Exception:
                reasons.add("viewer.parquet_unavailable")
                details["repositories"].append(repo_detail)
                continue
            raw_parquet = (
                parquet_response.get("parquet_files")
                if isinstance(parquet_response, Mapping)
                else None
            )
            if not isinstance(raw_parquet, list):
                reasons.add("viewer.parquet_malformed")
            else:
                by_config: dict[str, int] = {}
                for item in raw_parquet:
                    if not isinstance(item, Mapping):
                        reasons.add("viewer.parquet_item_malformed")
                        continue
                    config = str(item.get("config") or "")
                    size = item.get("size")
                    if not config or type(size) is not int or size < 0:
                        reasons.add("viewer.parquet_binding_invalid")
                        continue
                    by_config[config] = by_config.get(config, 0) + 1
                expected_counts: dict[str, int] = {}
                for shard in repo.parquet_shards:
                    expected_counts[shard.config_name] = (
                        expected_counts.get(shard.config_name, 0) + 1
                    )
                if by_config != expected_counts:
                    reasons.add("viewer.parquet_count_mismatch")
                    repo_detail["parquet_actual"] = by_config
                    repo_detail["parquet_expected"] = expected_counts

            for config in repo.config_names:
                try:
                    rows_response = gateway.viewer(
                        "rows",
                        {
                            "dataset": dataset,
                            "config": config,
                            "split": "train",
                        },
                    )
                except CredentialPrematureError:
                    raise
                except Exception:
                    reasons.add("viewer.rows_unavailable")
                    continue
                if not isinstance(rows_response, Mapping):
                    reasons.add("viewer.rows_malformed")
                    continue
                features = rows_response.get("features")
                if not features:
                    reasons.add("viewer.rows_features_missing")
                elif not isinstance(features, list):
                    reasons.add("viewer.rows_features_malformed")
                else:
                    names = []
                    for item in features:
                        if not isinstance(item, Mapping) or "name" not in item:
                            reasons.add("viewer.rows_features_malformed")
                            break
                        names.append(str(item["name"]))
                    expected_features = list(_features_for_config(repo, config))
                    if expected_features and names and names != expected_features:
                        reasons.add("viewer.rows_features_mismatch")
                raw_rows = rows_response.get("rows")
                if not isinstance(raw_rows, list):
                    reasons.add("viewer.rows_malformed")
                elif (
                    int(repo.config_row_counts.get(config, 0)) > 0
                    and len(raw_rows) == 0
                ):
                    reasons.add("viewer.rows_empty")

            try:
                size = gateway.viewer("size", {"dataset": dataset})
            except CredentialPrematureError:
                raise
            except Exception:
                reasons.add("viewer.size_unavailable")
                details["repositories"].append(repo_detail)
                continue
            if not isinstance(size, Mapping):
                reasons.add("viewer.size_malformed")
            else:
                configs = size.get("configs")
                if not isinstance(configs, Mapping):
                    reasons.add("viewer.size_dataset_missing")
                else:
                    for name, count in repo.config_row_counts.items():
                        entry = configs.get(name)
                        if not isinstance(entry, Mapping):
                            reasons.add("viewer.size_rows_invalid")
                            continue
                        try:
                            if int(entry.get("num_rows", -1)) != int(count):
                                reasons.add("viewer.size_rows_mismatch")
                        except (TypeError, ValueError):
                            reasons.add("viewer.size_rows_invalid")
                try:
                    total = int(size.get("num_rows", -1))
                    if total != int(repo.total_row_count):
                        reasons.add("viewer.size_rows_mismatch")
                except (TypeError, ValueError):
                    reasons.add("viewer.size_rows_invalid")

            try:
                stats = gateway.viewer("statistics", {"dataset": dataset})
            except CredentialPrematureError:
                raise
            except Exception:
                reasons.add("viewer.statistics_unavailable")
                details["repositories"].append(repo_detail)
                continue
            if not isinstance(stats, Mapping):
                reasons.add("viewer.statistics_malformed")
            else:
                items = stats.get("statistics")
                if not isinstance(items, list):
                    reasons.add("viewer.statistics_malformed")
                elif not items and repo.config_names:
                    reasons.add("viewer.statistics_empty")
                elif isinstance(items, list):
                    reported = {
                        str(item.get("config") or "")
                        for item in items
                        if isinstance(item, Mapping)
                    }
                    if not set(repo.config_names).issubset(reported):
                        reasons.add("viewer.statistics_config_mismatch")

            details["repositories"].append(repo_detail)

        return GateResult(
            name="dataset_viewer",
            passed=not reasons,
            reason_codes=tuple(sorted(reasons)),
            details=details,
        )


# ---------------------------------------------------------------------------
# Inventory loaders
# ---------------------------------------------------------------------------


def load_staged_release_inventory(root: str | Path) -> StagedReleaseInventory:
    """Load a staged multi-repo release tree into a normalized inventory."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ReleasePolicyV2Error(
            f"staged release root is not a directory: {base}"
        )
    support_paths: list[str] = []
    manifest: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    for name, target in (
        (RELEASE_MANIFEST_FILENAME, "manifest"),
        (QUALITY_REPORT_FILENAME, "quality"),
        (POLICY_RECEIPT_FILENAME, "receipt"),
    ):
        path = base / name
        if path.is_file():
            support_paths.append(name)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ReleasePolicyV2Error(f"cannot read {name}: {exc}") from exc
            if not isinstance(payload, Mapping):
                raise ReleasePolicyV2Error(f"{name} must be a JSON object")
            if target == "manifest":
                manifest = dict(payload)
            elif target == "quality":
                quality = dict(payload)
            else:
                receipt = dict(payload)
    organization = str(manifest.get("organization") or ORGANIZATION).strip()
    repos_root = base / REPOS_DIRNAME
    repositories: list[RepositoryInventory] = []
    if repos_root.is_dir():
        for child in sorted(repos_root.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            repositories.append(
                _load_repository_inventory(
                    child, organization=organization, repository=child.name
                )
            )
    return StagedReleaseInventory(
        root=str(base),
        organization=organization,
        repositories=tuple(repositories),
        manifest=manifest,
        quality_report=quality,
        policy_receipt=receipt,
        support_paths=tuple(support_paths),
    )


def inventory_from_release_object(release: Any) -> StagedReleaseInventory:
    """Build an inventory from an in-memory ``PatentHuggingFaceReleaseV2``."""
    organization = str(getattr(release, "organization", ORGANIZATION) or ORGANIZATION)
    if hasattr(release, "manifest_dict"):
        manifest = dict(release.manifest_dict())
    else:
        manifest = dict(getattr(release, "manifest", {}) or {})
    if hasattr(release, "quality_report_dict"):
        quality = dict(release.quality_report_dict())
    else:
        quality = dict(getattr(release, "quality_report", {}) or {})
    receipt: dict[str, Any] = {}
    support_paths: list[str] = []
    for art in getattr(release, "support_artifacts", ()) or ():
        rel = getattr(art, "relative_path", None) or (
            art.get("relative_path") if isinstance(art, Mapping) else None
        )
        content = getattr(art, "content", None)
        if rel in (
            POLICY_RECEIPT_FILENAME,
            RELEASE_MANIFEST_FILENAME,
            QUALITY_REPORT_FILENAME,
            README_FILENAME,
            DATASET_CONFIGS_FILENAME,
            COVERAGE_FILENAME,
        ):
            support_paths.append(str(rel))
        if rel == POLICY_RECEIPT_FILENAME and content:
            try:
                if isinstance(content, bytes):
                    receipt = json.loads(content.decode("utf-8"))
                elif isinstance(content, Mapping):
                    receipt = dict(content)
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                receipt = {}
    repositories: list[RepositoryInventory] = []
    for repo in getattr(release, "repositories", ()) or ():
        repository = str(
            getattr(repo, "repository", None)
            or (repo.get("repository") if isinstance(repo, Mapping) else "")
            or ""
        )
        role = str(
            getattr(repo, "role", None)
            or (repo.get("role") if isinstance(repo, Mapping) else "")
            or "corpus"
        )
        dataset_id = str(
            getattr(repo, "dataset_id", None)
            or f"{organization}/{repository}"
        )
        relative_paths: list[str] = []
        shards: list[StagedParquetShard] = []
        config_counts: dict[str, int] = dict(
            getattr(repo, "config_row_counts", None)
            or (repo.get("config_row_counts") if isinstance(repo, Mapping) else {})
            or {}
        )
        has_readme = False
        has_configs = False
        has_coverage = False
        coverage_sources: list[Mapping[str, Any]] = []
        dataset_configs: dict[str, Any] = {}
        for art in getattr(repo, "artifacts", ()) or ():
            rel = str(
                getattr(art, "relative_path", None)
                or (art.get("relative_path") if isinstance(art, Mapping) else "")
            )
            content = getattr(art, "content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, bytes):
                content = b""
            relative_paths.append(rel)
            if rel == README_FILENAME or rel.endswith("/" + README_FILENAME):
                has_readme = True
            if rel == DATASET_CONFIGS_FILENAME or rel.endswith(
                "/" + DATASET_CONFIGS_FILENAME
            ):
                has_configs = True
                try:
                    dataset_configs = json.loads(content.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    dataset_configs = {}
            if rel == COVERAGE_FILENAME or rel.endswith("/" + COVERAGE_FILENAME):
                has_coverage = True
                try:
                    cov = json.loads(content.decode("utf-8"))
                    sources = cov.get("sources") if isinstance(cov, Mapping) else None
                    if isinstance(sources, list):
                        coverage_sources = [
                            dict(item)
                            for item in sources
                            if isinstance(item, Mapping)
                        ]
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            if rel.endswith(".parquet"):
                config_name = _config_name_from_path(rel)
                parts = PurePosixPath(rel).parts
                if len(parts) >= 2 and parts[0] == "data":
                    config_name = parts[1] if parts[1] not in ("bm25", "graph") else config_name
                row_count = int(getattr(art, "row_count", 0) or 0)
                sha = str(
                    getattr(art, "sha256", None)
                    or _sha256_bytes(content)
                )
                shards.append(
                    StagedParquetShard(
                        relative_path=rel,
                        repository=repository,
                        config_name=config_name,
                        sha256=sha,
                        size_bytes=len(content),
                        row_count=row_count,
                        content=content,
                    )
                )
        config_names = tuple(
            sorted(
                {
                    s.config_name
                    for s in shards
                    if s.config_name
                }
                | set(config_counts)
            )
        )
        repositories.append(
            RepositoryInventory(
                repository=repository,
                dataset_id=dataset_id,
                role=str(getattr(role, "value", role)),
                relative_paths=tuple(sorted(relative_paths)),
                parquet_shards=tuple(
                    sorted(shards, key=lambda s: s.relative_path)
                ),
                config_names=config_names,
                config_row_counts=config_counts,
                has_readme=has_readme,
                has_dataset_configs=has_configs,
                has_coverage=has_coverage,
                coverage_sources=tuple(coverage_sources),
                dataset_configs=dataset_configs
                if isinstance(dataset_configs, Mapping)
                else {},
            )
        )
    # Prefer release-level support artifacts for receipt if empty
    if not receipt and hasattr(release, "support_artifacts"):
        pass
    if not support_paths:
        support_paths = [
            RELEASE_MANIFEST_FILENAME,
            QUALITY_REPORT_FILENAME,
            POLICY_RECEIPT_FILENAME,
        ]
    # Populate receipt from policy if present on release
    if not receipt:
        receipt = {
            "admitted": True,
            "policy_version": RELEASE_POLICY_V2_VERSION,
        }
    return StagedReleaseInventory(
        root="staged_root",
        organization=organization,
        repositories=tuple(repositories),
        manifest=manifest,
        quality_report=quality,
        policy_receipt=receipt,
        support_paths=tuple(sorted(set(support_paths))),
    )


def _load_repository_inventory(
    repo_dir: Path, *, organization: str, repository: str
) -> RepositoryInventory:
    relative_paths: list[str] = []
    shards: list[StagedParquetShard] = []
    config_counts: dict[str, int] = {}
    has_readme = False
    has_configs = False
    has_coverage = False
    coverage_sources: list[Mapping[str, Any]] = []
    dataset_configs: dict[str, Any] = {}
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(repo_dir).as_posix()
        if rel.startswith("."):
            continue
        relative_paths.append(rel)
        if rel == README_FILENAME:
            has_readme = True
        if rel == DATASET_CONFIGS_FILENAME:
            has_configs = True
            try:
                dataset_configs = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                dataset_configs = {}
        if rel == COVERAGE_FILENAME:
            has_coverage = True
            try:
                cov = json.loads(path.read_text(encoding="utf-8"))
                sources = cov.get("sources") if isinstance(cov, Mapping) else None
                if isinstance(sources, list):
                    coverage_sources = [
                        dict(item) for item in sources if isinstance(item, Mapping)
                    ]
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        if rel.endswith(".parquet"):
            content = path.read_bytes()
            config_name = _config_name_from_path(rel)
            row_count = _parquet_row_count(content)
            sha = _sha256_bytes(content)
            shards.append(
                StagedParquetShard(
                    relative_path=rel,
                    repository=repository,
                    config_name=config_name,
                    sha256=sha,
                    size_bytes=len(content),
                    row_count=row_count,
                    content=content,
                )
            )
            config_counts[config_name] = config_counts.get(config_name, 0) + row_count
    # Prefer declared configs from dataset_configs.json
    config_names: tuple[str, ...]
    if isinstance(dataset_configs, Mapping):
        configs_list = dataset_configs.get("configs")
        if isinstance(configs_list, list):
            declared = []
            for item in configs_list:
                if isinstance(item, Mapping):
                    name = str(
                        item.get("config_name") or item.get("name") or ""
                    ).strip()
                    if name:
                        declared.append(name)
            if declared:
                config_names = tuple(sorted(set(declared)))
            else:
                config_names = tuple(sorted(config_counts))
        else:
            config_names = tuple(sorted(config_counts))
    else:
        config_names = tuple(sorted(config_counts))

    role = "unknown"
    if repository == CORPUS_REPOSITORY:
        role = "corpus"
    elif repository == VECTORS_REPOSITORY:
        role = "vectors"
    elif repository == BM25_REPOSITORY:
        role = "bm25"
    elif repository == KNOWLEDGE_GRAPH_REPOSITORY:
        role = "knowledge_graph"

    # Prefer repo-manifest counts when present
    repo_manifest = repo_dir / "repo-manifest.json"
    if repo_manifest.is_file():
        try:
            payload = json.loads(repo_manifest.read_text(encoding="utf-8"))
            declared_counts = payload.get("config_row_counts")
            if isinstance(declared_counts, Mapping):
                config_counts = {
                    str(k): int(v) for k, v in declared_counts.items()
                }
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            pass

    return RepositoryInventory(
        repository=repository,
        dataset_id=f"{organization}/{repository}",
        role=role,
        relative_paths=tuple(relative_paths),
        parquet_shards=tuple(sorted(shards, key=lambda s: s.relative_path)),
        config_names=config_names,
        config_row_counts=config_counts,
        has_readme=has_readme,
        has_dataset_configs=has_configs,
        has_coverage=has_coverage,
        coverage_sources=tuple(coverage_sources),
        dataset_configs=dataset_configs if isinstance(dataset_configs, Mapping) else {},
    )


def _config_name_from_path(relative_path: str) -> str:
    parts = PurePosixPath(relative_path).parts
    if not parts:
        return PurePosixPath(relative_path).stem
    if parts[0] == "data":
        if len(parts) >= 3 and parts[1] == "bm25":
            if parts[2] == "documents":
                return "bm25_documents"
            if parts[2] == "postings":
                return "bm25_postings"
            return f"bm25_{parts[2]}"
        if len(parts) >= 3 and parts[1] == "graph":
            if parts[2] == "nodes":
                return "graph_nodes"
            if parts[2] == "edges":
                return "graph_edges"
            return f"graph_{parts[2]}"
        if len(parts) >= 2:
            if parts[1] == "vectors":
                return "vectors"
            return parts[1]
    if parts[0] == "indexes":
        return PurePosixPath(relative_path).stem
    return PurePosixPath(relative_path).stem


def _parquet_row_count(content: bytes) -> int:
    if not content.startswith(PARQUET_MAGIC):
        return 0
    try:
        import io

        import pyarrow.parquet as pq

        return int(pq.ParquetFile(io.BytesIO(content)).metadata.num_rows)
    except Exception:
        return 0


def _features_for_config(
    repo: RepositoryInventory, config: str
) -> tuple[str, ...]:
    for shard in repo.parquet_shards:
        if shard.config_name != config or not shard.content:
            continue
        try:
            import io

            import pyarrow.parquet as pq

            table = pq.read_table(io.BytesIO(shard.content))
            return tuple(table.column_names)
        except Exception:
            continue
    # Stable default feature set when content is unavailable
    return ("record_id", "config_name", "classification")


def _structural_orphan_probe(inventory: StagedReleaseInventory) -> list[str]:
    """Best-effort orphan detection by reading staged parquet join columns."""
    orphans: list[str] = []
    corpus_ids: set[str] = set()
    node_ids: set[str] = set()
    document_ids: set[str] = set()

    def _read_column(shard: StagedParquetShard, column: str) -> list[Any]:
        if not shard.content:
            return []
        try:
            import io

            import pyarrow.parquet as pq

            table = pq.read_table(io.BytesIO(shard.content))
            if column not in table.column_names:
                return []
            return list(table.column(column).to_pylist())
        except Exception:
            return []

    for repo in inventory.repositories:
        for shard in repo.parquet_shards:
            if shard.config_name in (
                "usc",
                "cfr",
                "public_law",
                "federal_register",
                "projected_rules",
                "applications",
                "claims",
                "events",
                "office_actions",
                "citations",
            ):
                for value in _read_column(shard, "record_id"):
                    if isinstance(value, str):
                        corpus_ids.add(value)

    for repo in inventory.repositories:
        for shard in repo.parquet_shards:
            if shard.config_name in ("vectors", "vector_chunk_index"):
                for value in _read_column(shard, "corpus_record_id"):
                    if isinstance(value, str) and value and value not in corpus_ids:
                        orphans.append(
                            f"{shard.relative_path}:corpus_record_id={value}"
                        )
            if shard.config_name == "bm25_documents":
                for value in _read_column(shard, "record_id"):
                    if isinstance(value, str):
                        document_ids.add(value)
                for value in _read_column(shard, "corpus_record_id"):
                    if isinstance(value, str) and value and value not in corpus_ids:
                        orphans.append(
                            f"{shard.relative_path}:corpus_record_id={value}"
                        )
            if shard.config_name == "graph_nodes":
                for value in _read_column(shard, "node_id"):
                    if isinstance(value, str):
                        node_ids.add(value)
            if shard.config_name == "bm25_postings":
                for value in _read_column(shard, "document_id"):
                    if (
                        isinstance(value, str)
                        and value
                        and document_ids
                        and value not in document_ids
                    ):
                        orphans.append(
                            f"{shard.relative_path}:document_id={value}"
                        )
            if shard.config_name == "graph_edges":
                for column in ("src_node_id", "dst_node_id"):
                    for value in _read_column(shard, column):
                        if (
                            isinstance(value, str)
                            and value
                            and node_ids
                            and value not in node_ids
                        ):
                            orphans.append(
                                f"{shard.relative_path}:{column}={value}"
                            )
    return orphans[:64]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def evaluate_rows_admission(
    rows: Sequence[Mapping[str, Any] | Any],
) -> ReleaseAdmissionV2:
    return DEFAULT_RELEASE_POLICY_V2.evaluate_rows(rows)


def evaluate_staged_release_admission(
    root: str | Path,
    *,
    viewer_gateway: ViewerGateway | None = None,
    run_viewer_gate: bool = True,
) -> ReleaseAdmissionV2:
    return DEFAULT_RELEASE_POLICY_V2.evaluate_staged_tree(
        root, viewer_gateway=viewer_gateway, run_viewer_gate=run_viewer_gate
    )


def assert_public_release_admitted(
    decision: ReleaseAdmissionV2,
) -> ReleaseAdmissionV2:
    return decision.require_admitted()


__all__ = [
    "AdmissionRejectedError",
    "CANONICAL_REPOSITORIES",
    "CardConfigRejectedError",
    "CountParityRejectedError",
    "CredentialPrematureError",
    "DEFAULT_MAX_SOURCE_AGE_DAYS",
    "DEFAULT_RELEASE_POLICY_V2",
    "DatasetViewerGate",
    "FakeDatasetViewerService",
    "FakeViewerGateway",
    "FindingCategory",
    "GateResult",
    "MANDATORY_SOURCE_IDS",
    "OrphanRejectedError",
    "PARQUET_MAGIC",
    "ParquetRejectedError",
    "PatentHFReleasePolicyV2",
    "PolicyFindingV2",
    "PrivacyRejectedError",
    "RELEASE_POLICY_V2_SHA256",
    "RELEASE_POLICY_V2_VERSION",
    "ReleaseAdmissionV2",
    "ReleasePolicyV2Error",
    "RepositoryInventory",
    "RightsRejectedError",
    "StagedParquetShard",
    "StagedReleaseInventory",
    "StaleSourceRejectedError",
    "VIEWER_ENDPOINTS",
    "ViewerGateRejectedError",
    "ViewerGateway",
    "assert_credentials_unresolved",
    "assert_public_release_admitted",
    "credentials_are_resolved",
    "evaluate_rows_admission",
    "evaluate_staged_release_admission",
    "inventory_from_release_object",
    "load_staged_release_inventory",
]
