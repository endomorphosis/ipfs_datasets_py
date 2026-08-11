"""Evaluator-complete source-rights authorization contract for LCR-082.

The module deliberately exposes no authorization-time, path, freshness, subset,
or digest-verification overrides.  A public decision always starts with a full
``legal-source-rights-catalog-v2`` catalog, independently reloads and hashes the
canonical policy/schema/SPDX/LCR-002/LCR-048 artifacts, derives the complete
expected source/content-scope frontier, revalidates every evidence byte string,
and evaluates every expected record.  Fixture evidence is always structurally
non-authorizing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Exact identities and canonical paths
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-source-rights-policy-v2"
CATALOG_SCHEMA_VERSION: Final = "legal-source-rights-catalog-v2"
EVIDENCE_SCHEMA_VERSION: Final = "legal-source-rights-evidence-v1"
CONDITION_EVIDENCE_SCHEMA_VERSION: Final = "legal-source-rights-condition-evidence-v1"
SPDX_REGISTRY_SCHEMA_VERSION: Final = "spdx-license-registry-v1"

PROGRAM_ID: Final = "legal-corpora-reindex-v1"
CATALOG_PRODUCER: Final = "audit_legal_source_rights.py@2"
PRODUCER: Final = CATALOG_PRODUCER
VERIFIER_ID: Final = "legal-source-rights-verifier@1"

FIXTURE_TASK_ID: Final = "LCR-082"
FIXTURE_GOAL_ID: Final = "LCR-G144"
LIVE_TASK_ID: Final = "LCR-078"
LIVE_GOAL_ID: Final = "LCR-G141"
TASK_ID: Final = FIXTURE_TASK_ID
GOAL_ID: Final = FIXTURE_GOAL_ID

STATE_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
FEDERAL_DATASET_REPO_ID: Final = "justicedao/ipfs_federal_register"
TARGET_DATASET_REPO_IDS: Final = (
    STATE_DATASET_REPO_ID,
    FEDERAL_DATASET_REPO_ID,
)

FIXTURE_VERIFIER_CLOCK_UTC: Final = "2026-08-10T12:00:00Z"
MAX_EVIDENCE_AGE: Final = timedelta(days=90)
MAX_FUTURE_SKEW: Final = timedelta(0)
DEFAULT_MAX_EVIDENCE_AGE: Final = MAX_EVIDENCE_AGE
DEFAULT_MAX_FUTURE_SKEW: Final = MAX_FUTURE_SKEW

CANONICAL_LCR002_SHA256: Final = (
    "c6cef251435bfa5185543c402e24d14b79acd409f5ec904da058ff805e74499c"
)
CANONICAL_LCR048_SHA256: Final = (
    "9d23788763ee7258487c8b01e341837c3743d7edb051e1bbb63f39111c06e596"
)
LCR048_REVISION: Final = "720668ae016cc400916dda884c9005e03618edfa"
EXPECTED_STATE_SOURCE_COUNT: Final = 51
EXPECTED_FRONTIER_SIZE: Final = 57
CANONICAL_SPDX_PACKAGE_SHA256: Final = (
    "ae54403571de582157029f64eb4269bd01de61592493b918f11fed6c5a7d40ff"
)
CANONICAL_SPDX_ACTIVE_IDS_SHA256: Final = (
    "b1e02daaed636b0ea3379313ccb91f49f0f4ea114f51b7f5a004e1101979b2db"
)
CANONICAL_SPDX_DEPRECATED_IDS_SHA256: Final = (
    "764d539674ab2f43dd5dd61c80d7e350bd16b1f6c35440991806d52f2fabad17"
)
CANONICAL_LICENSE_REF_DIGESTS: Final = MappingProxyType(
    {
        "LicenseRef-US-State-Statutory-Text":
            "d48cb14da98ecaa1f06e2ba498b17cadd9f0adaea38ceb28d71759ed049c8508",
        "LicenseRef-US-Federal-Government-Work":
            "46cbe5c99f7016f4f9ced6344bb297581c2a78dbc2bdd91e93b188a025484e1d",
        "LicenseRef-Site-Presentation-Reserved":
            "e445a14ae5519d72e26458c8ba81e080bb403fb2d45bd41bd2485fe6126b0da6",
        "LicenseRef-Annotations-Reserved":
            "af79ff861db14427b987ea16dab361da37194d8eee69fc7e00ecb78073bcd610",
        "LicenseRef-Database-Content-Reserved":
            "b6d3f8abf435c9ea6cc789adab780b03e88cb57169fee2a9e16a21aad9580bb9",
    }
)

CURRENTNESS_DISCLAIMER: Final = (
    "Rights, terms, robots, review, seal, and conditional acquisition evidence "
    "is evaluated against a verifier-owned clock with an immutable maximum age "
    "of 90 days and zero future skew; fixture success cannot authorize publication."
)

_SCHEMA_RELATIVE_PATH: Final = Path("data/legal/legal_source_rights_catalog.schema.json")
_SPDX_RELATIVE_PATH: Final = Path("data/legal/spdx_license_registry.json")
_FIXTURE_RELATIVE_PATH: Final = Path("tests/fixtures/legal_ir/legal_source_rights_catalog.json")
_LIVE_RELATIVE_PATH: Final = Path("data/legal/legal_source_rights_catalog.json")
_POLICY_RELATIVE_PATH: Final = Path(
    "ipfs_datasets_py/processors/legal_data/legal_source_rights_policy.py"
)
_LCR002_RELATIVE_PATH: Final = Path("data/legal/state_laws/official_source_catalog.json")
_LCR048_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_baseline.json"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+\-]{0,159}$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+\-]*$")
_LICENSEREF_RE = re.compile(r"^LicenseRef-[A-Za-z0-9][A-Za-z0-9.+\-]{0,127}$")

JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalSourceRightsPolicyError(ValueError):
    code = "legal_source_rights_policy_error"


class CatalogSchemaError(LegalSourceRightsPolicyError):
    code = "catalog_schema_error"


class IdentityError(CatalogSchemaError):
    code = "identity_error"


class DigestMismatchError(CatalogSchemaError):
    code = "digest_mismatch_error"


class FrontierMismatchError(CatalogSchemaError):
    code = "frontier_mismatch_error"


class LicenseIdentityError(CatalogSchemaError):
    code = "license_identity_error"


class RightsAdmissionError(LegalSourceRightsPolicyError):
    code = "rights_admission_error"


class StaleEvidenceError(RightsAdmissionError):
    code = "stale_evidence_error"


class ScopeMismatchError(RightsAdmissionError):
    code = "scope_mismatch_error"


class ProhibitedScopeError(RightsAdmissionError):
    code = "prohibited_scope_error"


class UnknownRightsError(RightsAdmissionError):
    code = "unknown_rights_error"


class CardOnlyEvidenceError(RightsAdmissionError):
    code = "card_only_evidence_error"


class LiveEvidenceRequiredError(LegalSourceRightsPolicyError):
    code = "live_evidence_required_error"


# ---------------------------------------------------------------------------
# Strict primitives: no stripping, coercion, aliases, or defaults
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_schema_path() -> Path:
    return repository_root() / _SCHEMA_RELATIVE_PATH


def default_spdx_registry_path() -> Path:
    return repository_root() / _SPDX_RELATIVE_PATH


def default_fixture_catalog_path() -> Path:
    return repository_root() / _FIXTURE_RELATIVE_PATH


def default_live_catalog_path() -> Path:
    return repository_root() / _LIVE_RELATIVE_PATH


def default_policy_module_path() -> Path:
    return repository_root() / _POLICY_RELATIVE_PATH


def default_state_source_catalog_path() -> Path:
    return repository_root() / _LCR002_RELATIVE_PATH


def default_federal_baseline_path() -> Path:
    return repository_root() / _LCR048_RELATIVE_PATH


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CatalogSchemaError("value cannot be encoded as strict canonical JSON") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    if type(value) is not str:
        raise CatalogSchemaError("sha256_text requires an exact string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CatalogSchemaError("value cannot be encoded as strict canonical JSON") from exc
    return sha256_bytes(encoded)


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: Path) -> str:
    return sha256_bytes(_read_regular_file_once(path, context=str(path)))


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_regular_file_once(
    path: Path,
    *,
    context: str,
    maximum_bytes: int = 16_000_000,
) -> bytes:
    """Read one fixed regular file descriptor and reject links or replacement races."""

    if not isinstance(path, Path):
        raise CatalogSchemaError(f"{context} path must be verifier-owned")
    absolute = path.absolute()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CatalogSchemaError(f"{context} canonical file is missing or unreadable") from exc
    if resolved != absolute:
        raise CatalogSchemaError(f"{context} canonical path must not contain symlinks")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise CatalogSchemaError(f"{context} canonical file could not be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CatalogSchemaError(f"{context} canonical input must be a regular file")
        path_before = os.stat(absolute, follow_symlinks=False)
        if _stat_identity(before) != _stat_identity(path_before):
            raise CatalogSchemaError(f"{context} canonical path changed during open")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise CatalogSchemaError(
                    f"{context} canonical input exceeds {maximum_bytes} bytes"
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(absolute, follow_symlinks=False)
        if (
            _stat_identity(before) != _stat_identity(after)
            or _stat_identity(after) != _stat_identity(path_after)
            or total != after.st_size
        ):
            raise CatalogSchemaError(f"{context} canonical file changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise CatalogSchemaError(f"{context} canonical file read failed closed") from exc
    finally:
        os.close(descriptor)


def _reject_surrogates(value: Any, *, context: str) -> None:
    if type(value) is str:
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise CatalogSchemaError(f"{context} contains an unpaired Unicode surrogate")
        return
    if type(value) is list:
        for item in value:
            _reject_surrogates(item, context=context)
        return
    if type(value) is dict:
        for key, item in value.items():
            _reject_surrogates(key, context=context)
            _reject_surrogates(item, context=context)


def _strict_json_loads(raw_bytes: bytes, *, context: str) -> Any:
    if type(raw_bytes) is not bytes:
        raise CatalogSchemaError(f"{context} bytes must be exact")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CatalogSchemaError(f"{context} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise CatalogSchemaError(f"{context} contains non-finite JSON number {value}")

    def parse_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise CatalogSchemaError(f"{context} contains non-finite JSON number")
        return parsed

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
    except CatalogSchemaError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CatalogSchemaError(f"{context} is not strict UTF-8 JSON") from exc
    _reject_surrogates(payload, context=context)
    return payload


def _strict_string(
    value: Any,
    name: str,
    *,
    maximum: int = 4096,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise CatalogSchemaError(f"{name} must be an exact JSON string")
    if not allow_empty and value == "":
        raise CatalogSchemaError(f"{name} must not be empty")
    if value != value.strip():
        raise CatalogSchemaError(f"{name} must not contain leading/trailing whitespace")
    if "\x00" in value:
        raise CatalogSchemaError(f"{name} must not contain NUL")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CatalogSchemaError(f"{name} must not contain Unicode surrogates")
    if len(value) > maximum:
        raise CatalogSchemaError(f"{name} exceeds maximum length {maximum}")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CatalogSchemaError(f"{name} must be an exact JSON boolean")
    return value


def _strict_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CatalogSchemaError(f"{name} must be an integer >= {minimum}")
    return value


def _strict_sha256(value: Any, name: str) -> str:
    text = _strict_string(value, name, maximum=64)
    if not _SHA256_RE.fullmatch(text):
        raise CatalogSchemaError(f"{name} must be lowercase 64-character SHA-256")
    return text


def _strict_https_url(value: Any, name: str) -> str:
    text = _strict_string(value, name, maximum=2048)
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CatalogSchemaError(f"{name} must be an absolute credential-free HTTPS URL")
    return text


def _strict_canonical_source_url(value: Any, name: str) -> str:
    """Parse an exact source URL without rewriting byte-pinned legacy HTTP."""

    text = _strict_string(value, name, maximum=2048)
    parsed = urlparse(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CatalogSchemaError(
            f"{name} must be an absolute credential-free canonical HTTP(S) URL"
        )
    return text


def _strict_identifier(value: Any, name: str, *, maximum: int = 160) -> str:
    text = _strict_string(value, name, maximum=maximum)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise CatalogSchemaError(f"{name} has invalid identifier syntax: {text!r}")
    return text


def _strict_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise CatalogSchemaError(f"{name} must be an exact JSON object")
    if any(type(key) is not str for key in value):
        raise CatalogSchemaError(f"{name} keys must be exact strings")
    return value


def _strict_list(value: Any, name: str) -> list[Any]:
    if type(value) is not list:
        raise CatalogSchemaError(f"{name} must be an exact JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    context: str,
) -> None:
    actual = set(value)
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        raise CatalogSchemaError(
            f"{context} keys must be exact; missing={missing!r} extra={extra!r}"
        )


def parse_utc_timestamp(value: Any, *, name: str = "timestamp") -> datetime:
    text = _strict_string(value, name, maximum=40)
    if not _UTC_RE.fullmatch(text):
        raise CatalogSchemaError(f"{name} must be a strict RFC3339 UTC-Z timestamp")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise CatalogSchemaError(f"{name} is not a valid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise CatalogSchemaError("timestamp must be an aware datetime")
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_verifier_now() -> datetime:
    return parse_utc_timestamp(FIXTURE_VERIFIER_CLOCK_UTC, name="fixture_verifier_clock")


def _decode_bound_bytes(encoded: Any, digest: Any, *, context: str) -> bytes:
    text = _strict_string(encoded, f"{context}.bytes_base64", maximum=4_000_000)
    declared = _strict_sha256(digest, f"{context}.sha256")
    try:
        decoded = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise CatalogSchemaError(f"{context}.bytes_base64 is not canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != text:
        raise CatalogSchemaError(f"{context}.bytes_base64 is not canonical base64")
    computed = sha256_bytes(decoded)
    if computed != declared:
        raise DigestMismatchError(
            f"{context} digest mismatch: declared={declared} computed={computed}"
        )
    return decoded


def _identity_for_mode(mode: "EvidenceMode") -> tuple[str, str, str]:
    if mode is EvidenceMode.FIXTURE:
        return FIXTURE_TASK_ID, FIXTURE_GOAL_ID, EvidenceMode.FIXTURE.value
    return LIVE_TASK_ID, LIVE_GOAL_ID, EvidenceMode.LIVE.value


# ---------------------------------------------------------------------------
# Exact enums
# ---------------------------------------------------------------------------


class CorpusFamily(str, Enum):
    STATE_LAWS = "state_laws"
    FEDERAL_REGISTER = "federal_register"

    @classmethod
    def parse(cls, value: Any, *, name: str = "corpus_family") -> "CorpusFamily":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc

    @property
    def dataset_repo_id(self) -> str:
        if self is CorpusFamily.STATE_LAWS:
            return STATE_DATASET_REPO_ID
        return FEDERAL_DATASET_REPO_ID


class ContentScope(str, Enum):
    STATUTORY_TEXT = "statutory_text"
    FEDERAL_GOVERNMENT_TEXT = "federal_government_text"
    SITE_PRESENTATION = "site_presentation"
    ANNOTATIONS = "annotations"
    EDITORIAL_ENHANCEMENTS = "editorial_enhancements"
    DATABASE_CONTENT = "database_content"

    @classmethod
    def parse(cls, value: Any, *, name: str = "content_scope") -> "ContentScope":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc


ADMISSIBLE_CONTENT_SCOPES: Final = frozenset(
    {ContentScope.STATUTORY_TEXT, ContentScope.FEDERAL_GOVERNMENT_TEXT}
)
DEFAULT_QUARANTINED_CONTENT_SCOPES: Final = frozenset(
    {
        ContentScope.SITE_PRESENTATION,
        ContentScope.ANNOTATIONS,
        ContentScope.EDITORIAL_ENHANCEMENTS,
        ContentScope.DATABASE_CONTENT,
    }
)


class RightsDisposition(str, Enum):
    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"

    @classmethod
    def parse(
        cls, value: Any, *, name: str = "rights_disposition"
    ) -> "RightsDisposition":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc


class RobotsAccessDisposition(str, Enum):
    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    DENIED = "denied"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"

    @classmethod
    def parse(
        cls, value: Any, *, name: str = "robots_access_disposition"
    ) -> "RobotsAccessDisposition":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc


class ReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @classmethod
    def parse(cls, value: Any, *, name: str = "review_status") -> "ReviewStatus":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc


class LegalBasis(str, Enum):
    US_GOVERNMENT_WORK = "us_government_work"
    GOVERNMENT_EDICTS_DOCTRINE = "government_edicts_doctrine"
    PUBLIC_DOMAIN = "public_domain"
    EXPLICIT_LICENSE = "explicit_license"
    STATUTORY_PERMISSION = "statutory_permission"
    UNKNOWN = "unknown"
    PROPRIETARY = "proprietary"
    NOT_APPLICABLE = "not_applicable"

    @classmethod
    def parse(cls, value: Any, *, name: str = "legal_basis") -> "LegalBasis":
        text = _strict_string(value, name, maximum=64)
        try:
            return cls(text)
        except ValueError as exc:
            raise CatalogSchemaError(f"{name} is unknown: {text!r}") from exc

    @property
    def supports_admission(self) -> bool:
        return self in {
            LegalBasis.US_GOVERNMENT_WORK,
            LegalBasis.GOVERNMENT_EDICTS_DOCTRINE,
            LegalBasis.PUBLIC_DOMAIN,
            LegalBasis.EXPLICIT_LICENSE,
            LegalBasis.STATUTORY_PERMISSION,
        }


class EvidenceMode(str, Enum):
    FIXTURE = "fixture"
    LIVE = "live"

    @classmethod
    def parse(cls, value: Any, *, name: str = "evidence_mode") -> "EvidenceMode":
        text = _strict_string(value, name, maximum=16)
        try:
            return cls(text)
        except ValueError as exc:
            raise IdentityError(f"{name} is unknown: {text!r}") from exc


# ---------------------------------------------------------------------------
# Complete SPDX snapshot and registered LicenseRefs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseRefDefinition:
    license_id: str
    definition_url: str
    definition_bytes_base64: str
    definition_sha256: str
    definition_digest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "definition_url": self.definition_url,
            "definition_bytes_base64": self.definition_bytes_base64,
            "definition_sha256": self.definition_sha256,
            "definition_digest_sha256": self.definition_digest_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> "LicenseRefDefinition":
        raw = _strict_mapping(value, context)
        required = (
            "license_id",
            "definition_url",
            "definition_bytes_base64",
            "definition_sha256",
            "definition_digest_sha256",
        )
        _exact_keys(raw, required=required, context=context)
        license_id = _strict_string(raw["license_id"], f"{context}.license_id", maximum=160)
        if not _LICENSEREF_RE.fullmatch(license_id):
            raise LicenseIdentityError(f"{context}.license_id is not a valid LicenseRef")
        definition_url = _strict_https_url(raw["definition_url"], f"{context}.definition_url")
        encoded = _strict_string(
            raw["definition_bytes_base64"],
            f"{context}.definition_bytes_base64",
            maximum=1_500_000,
        )
        digest = _strict_sha256(raw["definition_sha256"], f"{context}.definition_sha256")
        _decode_bound_bytes(encoded, digest, context=f"{context}.definition")
        sealed = _strict_sha256(
            raw["definition_digest_sha256"], f"{context}.definition_digest_sha256"
        )
        body = dict(raw)
        body.pop("definition_digest_sha256")
        computed = sha256_json(body)
        if sealed != computed:
            raise DigestMismatchError(
                f"{context}.definition_digest_sha256 mismatch: "
                f"declared={sealed} computed={computed}"
            )
        return cls(license_id, definition_url, encoded, digest, sealed)


@dataclass(frozen=True)
class SpdxLicenseRegistry:
    source_release_identifier: str
    active_ids: frozenset[str]
    deprecated_ids: frozenset[str]
    license_refs: Mapping[str, LicenseRefDefinition]
    registry_digest_sha256: str
    active_license_count: int
    deprecated_license_count: int

    def is_admissible(self, license_id: str) -> bool:
        return license_id in self.active_ids

    def license_ref(self, license_id: str) -> LicenseRefDefinition | None:
        return self.license_refs.get(license_id)

    @classmethod
    def from_mapping(cls, value: Any, *, context: str = "spdx_registry") -> "SpdxLicenseRegistry":
        raw = _strict_mapping(value, context)
        required = (
            "schema_version",
            "registry_id",
            "program_id",
            "source_authority",
            "source_release_identifier",
            "source_repository",
            "source_package_bytes_base64",
            "source_package_sha256",
            "active_ids_source_bytes_base64",
            "active_ids_source_sha256",
            "deprecated_ids_source_bytes_base64",
            "deprecated_ids_source_sha256",
            "active_license_count",
            "deprecated_license_count",
            "license_refs",
            "registry_digest_sha256",
        )
        _exact_keys(raw, required=required, context=context)
        if _strict_string(raw["schema_version"], f"{context}.schema_version") != SPDX_REGISTRY_SCHEMA_VERSION:
            raise IdentityError(f"{context}.schema_version is not exact")
        if _strict_string(raw["registry_id"], f"{context}.registry_id") != "legal-corpora-reindex-spdx-license-registry":
            raise IdentityError(f"{context}.registry_id is not exact")
        if _strict_string(raw["program_id"], f"{context}.program_id") != PROGRAM_ID:
            raise IdentityError(f"{context}.program_id is not exact")
        source_authority = _strict_https_url(
            raw["source_authority"], f"{context}.source_authority"
        )
        source_repository = _strict_https_url(
            raw["source_repository"], f"{context}.source_repository"
        )
        if source_authority != "https://spdx.org/licenses/":
            raise IdentityError(f"{context}.source_authority is not exact")
        if source_repository != "https://github.com/jslicense/spdx-license-ids":
            raise IdentityError(f"{context}.source_repository is not exact")

        package_encoded = _strict_string(
            raw["source_package_bytes_base64"],
            f"{context}.source_package_bytes_base64",
            maximum=100_000,
        )
        package_sha = _strict_sha256(
            raw["source_package_sha256"], f"{context}.source_package_sha256"
        )
        if package_sha != CANONICAL_SPDX_PACKAGE_SHA256:
            raise DigestMismatchError(
                f"{context}.source_package_sha256 is not the canonical release digest"
            )
        package_bytes = _decode_bound_bytes(
            package_encoded, package_sha, context=f"{context}.source_package"
        )
        package = _strict_json_loads(
            package_bytes, context=f"{context}.source_package"
        )
        if type(package) is not dict:
            raise CatalogSchemaError(f"{context}.source_package must decode to an object")
        if package.get("name") != "spdx-license-ids" or package.get("version") != "3.0.12":
            raise IdentityError(f"{context}.source package name/version is not exact")
        if package.get("repository") != "jslicense/spdx-license-ids":
            raise IdentityError(f"{context}.source package repository is not exact")
        release_id = _strict_string(
            raw["source_release_identifier"], f"{context}.source_release_identifier"
        )
        if release_id != f"spdx-license-ids@{package['version']}":
            raise IdentityError(f"{context}.source_release_identifier is not byte-bound to package")

        def parse_id_source(prefix: str) -> tuple[list[str], frozenset[str]]:
            encoded = _strict_string(
                raw[f"{prefix}_ids_source_bytes_base64"],
                f"{context}.{prefix}_ids_source_bytes_base64",
                maximum=500_000,
            )
            digest = _strict_sha256(
                raw[f"{prefix}_ids_source_sha256"],
                f"{context}.{prefix}_ids_source_sha256",
            )
            expected_source_digest = {
                "active": CANONICAL_SPDX_ACTIVE_IDS_SHA256,
                "deprecated": CANONICAL_SPDX_DEPRECATED_IDS_SHA256,
            }[prefix]
            if digest != expected_source_digest:
                raise DigestMismatchError(
                    f"{context}.{prefix}_ids_source_sha256 is not the canonical release digest"
                )
            source_bytes = _decode_bound_bytes(
                encoded, digest, context=f"{context}.{prefix}_ids_source"
            )
            values = _strict_json_loads(
                source_bytes, context=f"{context}.{prefix}_ids_source"
            )
            items = _strict_list(values, f"{context}.{prefix}_ids")
            parsed: list[str] = []
            for index, item in enumerate(items):
                license_id = _strict_string(
                    item, f"{context}.{prefix}_ids[{index}]", maximum=160
                )
                if not _SPDX_RE.fullmatch(license_id) or _LICENSEREF_RE.fullmatch(license_id):
                    raise LicenseIdentityError(
                        f"{context}.{prefix}_ids[{index}] has invalid SPDX identifier"
                    )
                parsed.append(license_id)
            if parsed != sorted(parsed) or len(parsed) != len(set(parsed)):
                raise CatalogSchemaError(
                    f"{context}.{prefix}_ids must be the complete sorted unique source list"
                )
            return parsed, frozenset(parsed)

        active_list, active = parse_id_source("active")
        deprecated_list, deprecated = parse_id_source("deprecated")
        active_count = _strict_int(
            raw["active_license_count"], f"{context}.active_license_count", minimum=1
        )
        deprecated_count = _strict_int(
            raw["deprecated_license_count"],
            f"{context}.deprecated_license_count",
            minimum=1,
        )
        if (
            active_count != len(active_list)
            or deprecated_count != len(deprecated_list)
            or active_count != 465
            or deprecated_count != 25
        ):
            raise CatalogSchemaError(f"{context} declared SPDX counts do not match source bytes")
        if active & deprecated:
            raise CatalogSchemaError(f"{context} active/deprecated SPDX sets overlap")

        refs_raw = _strict_list(raw["license_refs"], f"{context}.license_refs")
        refs: dict[str, LicenseRefDefinition] = {}
        for index, item in enumerate(refs_raw):
            definition = LicenseRefDefinition.from_mapping(
                item, context=f"{context}.license_refs[{index}]"
            )
            if definition.license_id in refs:
                raise LicenseIdentityError(f"duplicate registered LicenseRef {definition.license_id!r}")
            refs[definition.license_id] = definition
        actual_ref_digests = {
            license_id: definition.definition_digest_sha256
            for license_id, definition in refs.items()
        }
        if actual_ref_digests != dict(CANONICAL_LICENSE_REF_DIGESTS):
            raise LicenseIdentityError(
                f"{context}.license_refs must exactly equal the canonical registered definitions"
            )

        declared_registry_digest = _strict_sha256(
            raw["registry_digest_sha256"], f"{context}.registry_digest_sha256"
        )
        registry_body = dict(raw)
        registry_body.pop("registry_digest_sha256")
        computed_registry_digest = sha256_json(registry_body)
        if declared_registry_digest != computed_registry_digest:
            raise DigestMismatchError(
                f"{context}.registry_digest_sha256 mismatch: "
                f"declared={declared_registry_digest} computed={computed_registry_digest}"
            )
        return cls(
            source_release_identifier=release_id,
            active_ids=active,
            deprecated_ids=deprecated,
            license_refs=MappingProxyType(refs),
            registry_digest_sha256=declared_registry_digest,
            active_license_count=active_count,
            deprecated_license_count=deprecated_count,
        )


def load_spdx_registry() -> SpdxLicenseRegistry:
    path = default_spdx_registry_path()
    raw_bytes = _read_regular_file_once(path, context="canonical SPDX registry")
    payload = _strict_json_loads(raw_bytes, context="canonical SPDX registry")
    return SpdxLicenseRegistry.from_mapping(payload)


def get_spdx_registry() -> SpdxLicenseRegistry:
    # Intentionally uncached: parsing and evaluation must observe byte mutation.
    return load_spdx_registry()


def clear_spdx_registry_cache() -> None:
    # Compatibility no-op; this contract deliberately has no registry cache.
    return None


def is_licenseref(value: str) -> bool:
    return type(value) is str and bool(_LICENSEREF_RE.fullmatch(value))


def _normalize_spdx_against_registry(
    value: Any,
    *,
    name: str,
    registry: SpdxLicenseRegistry,
) -> str:
    text = _strict_string(value, name, maximum=160)
    if is_licenseref(text):
        if registry.license_ref(text) is None:
            raise LicenseIdentityError(f"{name} is an unregistered LicenseRef: {text!r}")
        return text
    if text in registry.deprecated_ids:
        raise LicenseIdentityError(f"{name} is a deprecated SPDX identifier: {text!r}")
    if text not in registry.active_ids:
        case_match = next(
            (
                item
                for item in registry.active_ids | registry.deprecated_ids
                if item.lower() == text.lower()
            ),
            None,
        )
        if case_match is not None:
            raise LicenseIdentityError(
                f"{name} is not the exact canonical SPDX identifier {case_match!r}"
            )
        raise LicenseIdentityError(
            f"{name} is invented, aliased, unknown, or omitted from the complete registry: {text!r}"
        )
    return text


def normalize_spdx(value: Any, *, name: str = "license_spdx") -> str:
    """Validate against the fixed canonical registry; no registry injection exists."""

    return _normalize_spdx_against_registry(
        value,
        name=name,
        registry=load_spdx_registry(),
    )


# ---------------------------------------------------------------------------
# Independently derived full LCR-002/LCR-048 frontier
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class ScopeFrontierEntry:
    source_id: str
    content_scope: str
    corpus_family: str
    dataset_repo_id: str
    source_url: str
    jurisdiction_or_authority: str
    origin: str

    def key(self) -> tuple[str, str]:
        return self.source_id, self.content_scope

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "content_scope": self.content_scope,
            "corpus_family": self.corpus_family,
            "dataset_repo_id": self.dataset_repo_id,
            "source_url": self.source_url,
            "jurisdiction_or_authority": self.jurisdiction_or_authority,
            "origin": self.origin,
        }


def _load_digest_pinned_json(path: Path, digest: str, *, context: str) -> Mapping[str, Any]:
    raw_bytes = _read_regular_file_once(path, context=f"{context} canonical evidence")
    computed = sha256_bytes(raw_bytes)
    if computed != digest:
        raise DigestMismatchError(
            f"{context} canonical evidence digest mismatch: declared={digest} computed={computed}"
        )
    payload = _strict_json_loads(raw_bytes, context=f"{context} canonical evidence")
    return _strict_mapping(payload, context)


def _derive_expected_scope_frontier_from_documents(
    state: Mapping[str, Any],
    federal: Mapping[str, Any],
) -> tuple[ScopeFrontierEntry, ...]:
    """Derive every expected source/scope from already verified evidence bytes.

    LCR-002 contributes all 51 official state acquisition paths as statutory
    text sources.  Its Oregon path additionally supplies the explicit
    presentation/annotation separation inherited from LCR-077.  LCR-048
    contributes its exact pinned Federal repository source projected across
    government text, presentation, editorial, and database layers.
    """

    if state.get("schema_version") != "state-laws-official-source-catalog-v1":
        raise FrontierMismatchError("LCR-002 schema_version is not exact")
    if state.get("task_id") != "LCR-002":
        raise FrontierMismatchError("LCR-002 task_id is not exact")
    jurisdictions = _strict_list(state.get("jurisdictions"), "LCR-002.jurisdictions")
    if len(jurisdictions) != EXPECTED_STATE_SOURCE_COUNT:
        raise FrontierMismatchError(
            f"LCR-002 must contain all {EXPECTED_STATE_SOURCE_COUNT} jurisdictions"
        )

    entries: list[ScopeFrontierEntry] = []
    postal_codes: set[str] = set()
    source_ids: set[str] = set()
    oregon_entry: ScopeFrontierEntry | None = None
    for index, raw_jurisdiction in enumerate(jurisdictions):
        jurisdiction = _strict_mapping(raw_jurisdiction, f"LCR-002.jurisdictions[{index}]")
        postal = _strict_string(
            jurisdiction.get("postal_code"), f"LCR-002.jurisdictions[{index}].postal_code", maximum=2
        )
        if not re.fullmatch(r"[A-Z]{2}", postal) or postal in postal_codes:
            raise FrontierMismatchError(f"LCR-002 postal code is invalid or duplicated: {postal!r}")
        postal_codes.add(postal)
        paths = _strict_list(
            jurisdiction.get("acquisition_paths"),
            f"LCR-002.jurisdictions[{index}].acquisition_paths",
        )
        if len(paths) != 1:
            raise FrontierMismatchError(
                f"LCR-002 {postal} must expose exactly one canonical acquisition path"
            )
        path = _strict_mapping(paths[0], f"LCR-002.{postal}.acquisition_paths[0]")
        source_id = _strict_identifier(path.get("path_id"), f"LCR-002.{postal}.path_id")
        if source_id in source_ids:
            raise FrontierMismatchError(f"LCR-002 duplicate path_id: {source_id!r}")
        source_ids.add(source_id)
        if path.get("authority_class") != "official":
            raise FrontierMismatchError(f"LCR-002 {source_id} is not an official source")
        source_url = _strict_canonical_source_url(
            path.get("entry_url"), f"LCR-002.{source_id}.entry_url"
        )
        entry = ScopeFrontierEntry(
            source_id=source_id,
            content_scope=ContentScope.STATUTORY_TEXT.value,
            corpus_family=CorpusFamily.STATE_LAWS.value,
            dataset_repo_id=STATE_DATASET_REPO_ID,
            source_url=source_url,
            jurisdiction_or_authority=postal,
            origin="LCR-002",
        )
        entries.append(entry)
        if postal == "OR":
            oregon_entry = entry

    if oregon_entry is None or oregon_entry.source_id != "or-legislature-ors":
        raise FrontierMismatchError("LCR-002 canonical Oregon path is missing")
    for scope in (ContentScope.SITE_PRESENTATION, ContentScope.ANNOTATIONS):
        entries.append(
            ScopeFrontierEntry(
                source_id=oregon_entry.source_id,
                content_scope=scope.value,
                corpus_family=oregon_entry.corpus_family,
                dataset_repo_id=oregon_entry.dataset_repo_id,
                source_url=oregon_entry.source_url,
                jurisdiction_or_authority=oregon_entry.jurisdiction_or_authority,
                origin="LCR-002",
            )
        )

    if (
        federal.get("schema") != "ipfs_datasets_py/legal-corpora-reindex-federal-baseline@1"
        or federal.get("task_id") != "LCR-048"
        or federal.get("goal_id") != "LCR-G100"
        or federal.get("program_id") != PROGRAM_ID
    ):
        raise FrontierMismatchError("LCR-048 identity tuple is not exact")
    dataset = _strict_mapping(federal.get("dataset"), "LCR-048.dataset")
    if (
        dataset.get("repo_id") != FEDERAL_DATASET_REPO_ID
        or dataset.get("revision") != LCR048_REVISION
        or dataset.get("revision_pinned") is not True
    ):
        raise FrontierMismatchError("LCR-048 repository/revision binding is not exact")
    federal_source_id = f"fr-hf-baseline-{LCR048_REVISION}"
    federal_url = (
        "https://huggingface.co/datasets/justicedao/ipfs_federal_register/tree/"
        + LCR048_REVISION
    )
    for scope in (
        ContentScope.FEDERAL_GOVERNMENT_TEXT,
        ContentScope.SITE_PRESENTATION,
        ContentScope.EDITORIAL_ENHANCEMENTS,
        ContentScope.DATABASE_CONTENT,
    ):
        entries.append(
            ScopeFrontierEntry(
                source_id=federal_source_id,
                content_scope=scope.value,
                corpus_family=CorpusFamily.FEDERAL_REGISTER.value,
                dataset_repo_id=FEDERAL_DATASET_REPO_ID,
                source_url=federal_url,
                jurisdiction_or_authority="US-FR",
                origin="LCR-048",
            )
        )

    ordered = tuple(sorted(entries))
    if len(ordered) != EXPECTED_FRONTIER_SIZE:
        raise FrontierMismatchError(
            f"derived frontier size mismatch: {len(ordered)} != {EXPECTED_FRONTIER_SIZE}"
        )
    if len({entry.key() for entry in ordered}) != len(ordered):
        raise FrontierMismatchError("derived frontier contains duplicate source/scope keys")
    return ordered


def derive_expected_scope_frontier() -> tuple[ScopeFrontierEntry, ...]:
    """Derive the complete frontier from one read of each byte-pinned source."""

    state = _load_digest_pinned_json(
        default_state_source_catalog_path(), CANONICAL_LCR002_SHA256, context="LCR-002"
    )
    federal = _load_digest_pinned_json(
        default_federal_baseline_path(), CANONICAL_LCR048_SHA256, context="LCR-048"
    )
    return _derive_expected_scope_frontier_from_documents(state, federal)


def frontier_digest_sha256() -> str:
    """Digest only the independently derived canonical frontier."""

    entries = derive_expected_scope_frontier()
    return _frontier_digest(entries)


def _frontier_digest(entries: Sequence[ScopeFrontierEntry]) -> str:
    return sha256_json([entry.to_dict() for entry in sorted(entries)])


_ARTIFACT_DIGEST_KEYS: Final = (
    "policy_module_sha256",
    "schema_sha256",
    "spdx_registry_sha256",
    "lcr002_source_catalog_sha256",
    "lcr048_federal_baseline_sha256",
    "expected_scope_frontier_sha256",
)


@dataclass(frozen=True)
class _VerifierArtifacts:
    schema_document: Mapping[str, Any]
    registry: SpdxLicenseRegistry
    frontier: tuple[ScopeFrontierEntry, ...]
    digests: Mapping[str, str]


def _load_verifier_artifacts() -> _VerifierArtifacts:
    """Read, parse, and hash every canonical verifier input exactly once."""

    policy_bytes = _read_regular_file_once(
        default_policy_module_path(), context="canonical policy module"
    )
    schema_bytes = _read_regular_file_once(
        default_schema_path(), context="canonical source-rights schema"
    )
    registry_bytes = _read_regular_file_once(
        default_spdx_registry_path(), context="canonical SPDX registry"
    )
    state_bytes = _read_regular_file_once(
        default_state_source_catalog_path(), context="LCR-002 canonical evidence"
    )
    federal_bytes = _read_regular_file_once(
        default_federal_baseline_path(), context="LCR-048 canonical evidence"
    )
    state_digest = sha256_bytes(state_bytes)
    federal_digest = sha256_bytes(federal_bytes)
    if state_digest != CANONICAL_LCR002_SHA256:
        raise DigestMismatchError(
            "LCR-002 canonical evidence digest mismatch: "
            f"declared={CANONICAL_LCR002_SHA256} computed={state_digest}"
        )
    if federal_digest != CANONICAL_LCR048_SHA256:
        raise DigestMismatchError(
            "LCR-048 canonical evidence digest mismatch: "
            f"declared={CANONICAL_LCR048_SHA256} computed={federal_digest}"
        )
    schema_document = _strict_mapping(
        _strict_json_loads(schema_bytes, context="canonical source-rights schema"),
        "canonical source-rights schema",
    )
    registry_payload = _strict_mapping(
        _strict_json_loads(registry_bytes, context="canonical SPDX registry"),
        "canonical SPDX registry",
    )
    state = _strict_mapping(
        _strict_json_loads(state_bytes, context="LCR-002 canonical evidence"),
        "LCR-002 canonical evidence",
    )
    federal = _strict_mapping(
        _strict_json_loads(federal_bytes, context="LCR-048 canonical evidence"),
        "LCR-048 canonical evidence",
    )
    registry = SpdxLicenseRegistry.from_mapping(registry_payload)
    frontier = _derive_expected_scope_frontier_from_documents(state, federal)
    digests = MappingProxyType(
        {
            "policy_module_sha256": sha256_bytes(policy_bytes),
            "schema_sha256": sha256_bytes(schema_bytes),
            "spdx_registry_sha256": sha256_bytes(registry_bytes),
            "lcr002_source_catalog_sha256": state_digest,
            "lcr048_federal_baseline_sha256": federal_digest,
            "expected_scope_frontier_sha256": _frontier_digest(frontier),
        }
    )
    return _VerifierArtifacts(schema_document, registry, frontier, digests)


def compute_artifact_digests() -> dict[str, str]:
    # All paths are verifier-owned and fixed; callers cannot redirect them.
    return dict(_load_verifier_artifacts().digests)


def _require_artifact_digests_against(
    value: Any,
    *,
    expected: Mapping[str, str],
    context: str,
) -> Mapping[str, str]:
    raw = _strict_mapping(value, context)
    _exact_keys(raw, required=_ARTIFACT_DIGEST_KEYS, context=context)
    declared = {
        key: _strict_sha256(raw[key], f"{context}.{key}") for key in _ARTIFACT_DIGEST_KEYS
    }
    for key in _ARTIFACT_DIGEST_KEYS:
        if declared[key] != expected[key]:
            raise DigestMismatchError(
                f"{context}.{key} mismatch: declared={declared[key]} computed={expected[key]}"
            )
    return MappingProxyType(declared)


def require_artifact_digests(value: Any, *, context: str = "catalog.artifact_digests") -> Mapping[str, str]:
    return _require_artifact_digests_against(
        value,
        expected=_load_verifier_artifacts().digests,
        context=context,
    )


# ---------------------------------------------------------------------------
# Content-addressed evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceArtifact:
    schema_version: str
    evidence_kind: str
    producer: str
    program_id: str
    task_id: str
    goal_id: str
    evidence_mode: str
    verifier_id: str
    source_id: str
    content_scope: str
    url: str
    verifier_observed_at: str
    content_bytes_base64: str
    content_sha256: str
    evidence_digest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_kind": self.evidence_kind,
            "producer": self.producer,
            "program_id": self.program_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "evidence_mode": self.evidence_mode,
            "verifier_id": self.verifier_id,
            "source_id": self.source_id,
            "content_scope": self.content_scope,
            "url": self.url,
            "verifier_observed_at": self.verifier_observed_at,
            "content_bytes_base64": self.content_bytes_base64,
            "content_sha256": self.content_sha256,
            "evidence_digest_sha256": self.evidence_digest_sha256,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        context: str,
        expected_kind: str,
        expected_mode: EvidenceMode,
        expected_source_id: str,
        expected_scope: ContentScope,
        expected_url: str,
    ) -> "EvidenceArtifact":
        raw = _strict_mapping(value, context)
        required = (
            "schema_version",
            "evidence_kind",
            "producer",
            "program_id",
            "task_id",
            "goal_id",
            "evidence_mode",
            "verifier_id",
            "source_id",
            "content_scope",
            "url",
            "verifier_observed_at",
            "content_bytes_base64",
            "content_sha256",
            "evidence_digest_sha256",
        )
        _exact_keys(raw, required=required, context=context)
        task_id, goal_id, mode_text = _identity_for_mode(expected_mode)
        exact_values = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "evidence_kind": expected_kind,
            "producer": CATALOG_PRODUCER,
            "program_id": PROGRAM_ID,
            "task_id": task_id,
            "goal_id": goal_id,
            "evidence_mode": mode_text,
            "verifier_id": VERIFIER_ID,
            "source_id": expected_source_id,
            "content_scope": expected_scope.value,
        }
        parsed_values: dict[str, str] = {}
        for key, expected in exact_values.items():
            actual = _strict_string(raw[key], f"{context}.{key}", maximum=256)
            if actual != expected:
                raise IdentityError(
                    f"{context}.{key} must be exact {expected!r}, got {actual!r}"
                )
            parsed_values[key] = actual
        url = _strict_canonical_source_url(raw["url"], f"{context}.url")
        if url != expected_url:
            raise IdentityError(
                f"{context}.url must exactly bind the canonical source URL"
            )
        observed = _strict_string(
            raw["verifier_observed_at"], f"{context}.verifier_observed_at", maximum=40
        )
        parse_utc_timestamp(observed, name=f"{context}.verifier_observed_at")
        encoded = _strict_string(
            raw["content_bytes_base64"], f"{context}.content_bytes_base64", maximum=4_000_000
        )
        content_sha = _strict_sha256(raw["content_sha256"], f"{context}.content_sha256")
        _decode_bound_bytes(encoded, content_sha, context=f"{context}.content")
        evidence_digest = _strict_sha256(
            raw["evidence_digest_sha256"], f"{context}.evidence_digest_sha256"
        )
        body = dict(raw)
        body.pop("evidence_digest_sha256")
        computed = sha256_json(body)
        if computed != evidence_digest:
            raise DigestMismatchError(
                f"{context}.evidence_digest_sha256 mismatch: "
                f"declared={evidence_digest} computed={computed}"
            )
        return cls(
            schema_version=parsed_values["schema_version"],
            evidence_kind=parsed_values["evidence_kind"],
            producer=parsed_values["producer"],
            program_id=parsed_values["program_id"],
            task_id=parsed_values["task_id"],
            goal_id=parsed_values["goal_id"],
            evidence_mode=parsed_values["evidence_mode"],
            verifier_id=parsed_values["verifier_id"],
            source_id=parsed_values["source_id"],
            content_scope=parsed_values["content_scope"],
            url=url,
            verifier_observed_at=observed,
            content_bytes_base64=encoded,
            content_sha256=content_sha,
            evidence_digest_sha256=evidence_digest,
        )


@dataclass(frozen=True)
class ConditionEvidence:
    schema_version: str
    producer: str
    program_id: str
    task_id: str
    goal_id: str
    evidence_mode: str
    verifier_id: str
    condition_id: str
    source_id: str
    content_scope: str
    verifier_observed_at: str
    request_bytes_base64: str
    request_sha256: str
    response_bytes_base64: str
    response_sha256: str
    receipt_digest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "program_id": self.program_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "evidence_mode": self.evidence_mode,
            "verifier_id": self.verifier_id,
            "condition_id": self.condition_id,
            "source_id": self.source_id,
            "content_scope": self.content_scope,
            "verifier_observed_at": self.verifier_observed_at,
            "request_bytes_base64": self.request_bytes_base64,
            "request_sha256": self.request_sha256,
            "response_bytes_base64": self.response_bytes_base64,
            "response_sha256": self.response_sha256,
            "receipt_digest_sha256": self.receipt_digest_sha256,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        context: str,
        expected_mode: EvidenceMode,
        expected_source_id: str,
        expected_scope: ContentScope,
    ) -> "ConditionEvidence":
        raw = _strict_mapping(value, context)
        required = (
            "schema_version",
            "producer",
            "program_id",
            "task_id",
            "goal_id",
            "evidence_mode",
            "verifier_id",
            "condition_id",
            "source_id",
            "content_scope",
            "verifier_observed_at",
            "request_bytes_base64",
            "request_sha256",
            "response_bytes_base64",
            "response_sha256",
            "receipt_digest_sha256",
        )
        _exact_keys(raw, required=required, context=context)
        task_id, goal_id, mode_text = _identity_for_mode(expected_mode)
        exact_values = {
            "schema_version": CONDITION_EVIDENCE_SCHEMA_VERSION,
            "producer": CATALOG_PRODUCER,
            "program_id": PROGRAM_ID,
            "task_id": task_id,
            "goal_id": goal_id,
            "evidence_mode": mode_text,
            "verifier_id": VERIFIER_ID,
            "source_id": expected_source_id,
            "content_scope": expected_scope.value,
        }
        parsed_values: dict[str, str] = {}
        for key, expected in exact_values.items():
            actual = _strict_string(raw[key], f"{context}.{key}", maximum=256)
            if actual != expected:
                raise IdentityError(
                    f"{context}.{key} must be exact {expected!r}, got {actual!r}"
                )
            parsed_values[key] = actual
        condition_id = _strict_identifier(raw["condition_id"], f"{context}.condition_id")
        observed = _strict_string(
            raw["verifier_observed_at"], f"{context}.verifier_observed_at", maximum=40
        )
        parse_utc_timestamp(observed, name=f"{context}.verifier_observed_at")
        request_encoded = _strict_string(
            raw["request_bytes_base64"], f"{context}.request_bytes_base64", maximum=4_000_000
        )
        request_sha = _strict_sha256(raw["request_sha256"], f"{context}.request_sha256")
        _decode_bound_bytes(request_encoded, request_sha, context=f"{context}.request")
        response_encoded = _strict_string(
            raw["response_bytes_base64"], f"{context}.response_bytes_base64", maximum=4_000_000
        )
        response_sha = _strict_sha256(raw["response_sha256"], f"{context}.response_sha256")
        _decode_bound_bytes(response_encoded, response_sha, context=f"{context}.response")
        receipt_digest = _strict_sha256(
            raw["receipt_digest_sha256"], f"{context}.receipt_digest_sha256"
        )
        body = dict(raw)
        body.pop("receipt_digest_sha256")
        computed = sha256_json(body)
        if computed != receipt_digest:
            raise DigestMismatchError(
                f"{context}.receipt_digest_sha256 mismatch: "
                f"declared={receipt_digest} computed={computed}"
            )
        return cls(
            schema_version=parsed_values["schema_version"],
            producer=parsed_values["producer"],
            program_id=parsed_values["program_id"],
            task_id=parsed_values["task_id"],
            goal_id=parsed_values["goal_id"],
            evidence_mode=parsed_values["evidence_mode"],
            verifier_id=parsed_values["verifier_id"],
            condition_id=condition_id,
            source_id=parsed_values["source_id"],
            content_scope=parsed_values["content_scope"],
            verifier_observed_at=observed,
            request_bytes_base64=request_encoded,
            request_sha256=request_sha,
            response_bytes_base64=response_encoded,
            response_sha256=response_sha,
            receipt_digest_sha256=receipt_digest,
        )


@dataclass(frozen=True)
class Permissions:
    redistribution: bool
    derivatives: bool
    archive: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "redistribution": self.redistribution,
            "derivatives": self.derivatives,
            "archive": self.archive,
        }

    @classmethod
    def from_mapping(cls, value: Any, *, context: str) -> "Permissions":
        raw = _strict_mapping(value, context)
        _exact_keys(
            raw,
            required=("redistribution", "derivatives", "archive"),
            context=context,
        )
        return cls(
            redistribution=_strict_bool(raw["redistribution"], f"{context}.redistribution"),
            derivatives=_strict_bool(raw["derivatives"], f"{context}.derivatives"),
            archive=_strict_bool(raw["archive"], f"{context}.archive"),
        )

    def all_required_granted(self) -> bool:
        return self.redistribution and self.derivatives and self.archive


@dataclass(frozen=True)
class SourceRightsRecord:
    record_id: str
    source_id: str
    corpus_family: CorpusFamily
    dataset_repo_id: str
    content_scope: ContentScope
    rights_disposition: RightsDisposition
    license_spdx: str
    license_ref_digest_sha256: str | None
    legal_basis: LegalBasis
    terms: EvidenceArtifact
    robots: EvidenceArtifact
    robots_access_disposition: RobotsAccessDisposition
    access_conditions: tuple[str, ...]
    condition_evidence: tuple[ConditionEvidence, ...]
    permissions: Permissions
    attribution_notice: str
    review_status: ReviewStatus
    reviewed_at: str
    sealed_at: str
    source_url: str
    jurisdiction_or_authority: str
    card_label_is_not_authority: bool
    dataset_card_label: str | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "corpus_family": self.corpus_family.value,
            "dataset_repo_id": self.dataset_repo_id,
            "content_scope": self.content_scope.value,
            "rights_disposition": self.rights_disposition.value,
            "license_spdx": self.license_spdx,
            "license_ref_digest_sha256": self.license_ref_digest_sha256,
            "legal_basis": self.legal_basis.value,
            "terms": self.terms.to_dict(),
            "robots": self.robots.to_dict(),
            "robots_access_disposition": self.robots_access_disposition.value,
            "access_conditions": list(self.access_conditions),
            "condition_evidence": [item.to_dict() for item in self.condition_evidence],
            "permissions": self.permissions.to_dict(),
            "attribution_notice": self.attribution_notice,
            "review_status": self.review_status.value,
            "reviewed_at": self.reviewed_at,
            "sealed_at": self.sealed_at,
            "source_url": self.source_url,
            "jurisdiction_or_authority": self.jurisdiction_or_authority,
            "card_label_is_not_authority": self.card_label_is_not_authority,
            "dataset_card_label": self.dataset_card_label,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        context: str,
        evidence_mode: EvidenceMode,
        registry: SpdxLicenseRegistry,
    ) -> "SourceRightsRecord":
        raw = _strict_mapping(value, context)
        required = (
            "record_id",
            "source_id",
            "corpus_family",
            "dataset_repo_id",
            "content_scope",
            "rights_disposition",
            "license_spdx",
            "license_ref_digest_sha256",
            "legal_basis",
            "terms",
            "robots",
            "robots_access_disposition",
            "access_conditions",
            "condition_evidence",
            "permissions",
            "attribution_notice",
            "review_status",
            "reviewed_at",
            "sealed_at",
            "source_url",
            "jurisdiction_or_authority",
            "card_label_is_not_authority",
            "dataset_card_label",
            "notes",
        )
        _exact_keys(raw, required=required, context=context)
        record_id = _strict_identifier(raw["record_id"], f"{context}.record_id")
        source_id = _strict_identifier(raw["source_id"], f"{context}.source_id")
        corpus = CorpusFamily.parse(raw["corpus_family"], name=f"{context}.corpus_family")
        dataset_repo_id = _strict_string(
            raw["dataset_repo_id"], f"{context}.dataset_repo_id", maximum=128
        )
        if dataset_repo_id != corpus.dataset_repo_id:
            raise IdentityError(f"{context}.dataset_repo_id does not match corpus_family")
        scope = ContentScope.parse(raw["content_scope"], name=f"{context}.content_scope")
        source_url = _strict_canonical_source_url(
            raw["source_url"], f"{context}.source_url"
        )
        disposition = RightsDisposition.parse(
            raw["rights_disposition"], name=f"{context}.rights_disposition"
        )
        license_spdx = _normalize_spdx_against_registry(
            raw["license_spdx"], name=f"{context}.license_spdx", registry=registry
        )
        license_ref_digest_raw = raw["license_ref_digest_sha256"]
        license_ref_digest: str | None
        if is_licenseref(license_spdx):
            license_ref_digest = _strict_sha256(
                license_ref_digest_raw, f"{context}.license_ref_digest_sha256"
            )
            definition = registry.license_ref(license_spdx)
            if definition is None or definition.definition_digest_sha256 != license_ref_digest:
                raise LicenseIdentityError(
                    f"{context}.license_ref_digest_sha256 does not bind the registered LicenseRef"
                )
        else:
            if license_ref_digest_raw is not None:
                raise LicenseIdentityError(
                    f"{context}.license_ref_digest_sha256 must be null for canonical SPDX ids"
                )
            license_ref_digest = None
        legal_basis = LegalBasis.parse(raw["legal_basis"], name=f"{context}.legal_basis")
        terms = EvidenceArtifact.from_mapping(
            raw["terms"],
            context=f"{context}.terms",
            expected_kind="terms",
            expected_mode=evidence_mode,
            expected_source_id=source_id,
            expected_scope=scope,
            expected_url=source_url,
        )
        robots = EvidenceArtifact.from_mapping(
            raw["robots"],
            context=f"{context}.robots",
            expected_kind="robots",
            expected_mode=evidence_mode,
            expected_source_id=source_id,
            expected_scope=scope,
            expected_url=source_url,
        )
        robots_disposition = RobotsAccessDisposition.parse(
            raw["robots_access_disposition"],
            name=f"{context}.robots_access_disposition",
        )
        conditions_raw = _strict_list(raw["access_conditions"], f"{context}.access_conditions")
        conditions = tuple(
            _strict_identifier(item, f"{context}.access_conditions[{index}]")
            for index, item in enumerate(conditions_raw)
        )
        if len(conditions) != len(set(conditions)):
            raise CatalogSchemaError(f"{context}.access_conditions must be unique")
        receipts_raw = _strict_list(raw["condition_evidence"], f"{context}.condition_evidence")
        receipts = tuple(
            ConditionEvidence.from_mapping(
                item,
                context=f"{context}.condition_evidence[{index}]",
                expected_mode=evidence_mode,
                expected_source_id=source_id,
                expected_scope=scope,
            )
            for index, item in enumerate(receipts_raw)
        )
        if len({item.condition_id for item in receipts}) != len(receipts):
            raise CatalogSchemaError(f"{context}.condition_evidence IDs must be unique")
        permissions = Permissions.from_mapping(raw["permissions"], context=f"{context}.permissions")
        attribution = _strict_string(
            raw["attribution_notice"], f"{context}.attribution_notice", maximum=4096
        )
        review_status = ReviewStatus.parse(raw["review_status"], name=f"{context}.review_status")
        reviewed_at = _strict_string(raw["reviewed_at"], f"{context}.reviewed_at", maximum=40)
        parse_utc_timestamp(reviewed_at, name=f"{context}.reviewed_at")
        sealed_at = _strict_string(raw["sealed_at"], f"{context}.sealed_at", maximum=40)
        parse_utc_timestamp(sealed_at, name=f"{context}.sealed_at")
        authority = _strict_string(
            raw["jurisdiction_or_authority"],
            f"{context}.jurisdiction_or_authority",
            maximum=128,
        )
        if _strict_bool(
            raw["card_label_is_not_authority"], f"{context}.card_label_is_not_authority"
        ) is not True:
            raise CardOnlyEvidenceError(
                f"{context}.card_label_is_not_authority must be exactly true"
            )
        card_label_raw = raw["dataset_card_label"]
        if card_label_raw is None:
            card_label = None
        else:
            card_label = _strict_string(
                card_label_raw, f"{context}.dataset_card_label", maximum=128
            )
        notes = _strict_string(raw["notes"], f"{context}.notes", maximum=4096, allow_empty=True)
        return cls(
            record_id=record_id,
            source_id=source_id,
            corpus_family=corpus,
            dataset_repo_id=dataset_repo_id,
            content_scope=scope,
            rights_disposition=disposition,
            license_spdx=license_spdx,
            license_ref_digest_sha256=license_ref_digest,
            legal_basis=legal_basis,
            terms=terms,
            robots=robots,
            robots_access_disposition=robots_disposition,
            access_conditions=conditions,
            condition_evidence=receipts,
            permissions=permissions,
            attribution_notice=attribution,
            review_status=review_status,
            reviewed_at=reviewed_at,
            sealed_at=sealed_at,
            source_url=source_url,
            jurisdiction_or_authority=authority,
            card_label_is_not_authority=True,
            dataset_card_label=card_label,
            notes=notes,
        )


def _assert_records_match_frontier(
    records: Sequence[SourceRightsRecord],
    expected_entries: Sequence[ScopeFrontierEntry],
) -> None:
    """Require equality with the verifier-derived frontier; no frontier injection exists."""

    expected = {entry.key(): entry for entry in expected_entries}
    actual: dict[tuple[str, str], SourceRightsRecord] = {}
    for record in records:
        key = (record.source_id, record.content_scope.value)
        if key in actual:
            raise FrontierMismatchError(f"duplicate catalog source/scope key: {key!r}")
        actual[key] = record
    if set(actual) != set(expected):
        raise FrontierMismatchError(
            "catalog records must exactly equal the independently derived full frontier; "
            f"missing={sorted(set(expected) - set(actual))!r} "
            f"extra={sorted(set(actual) - set(expected))!r}"
        )
    for key, entry in expected.items():
        record = actual[key]
        expected_record_id = f"{entry.source_id}-{entry.content_scope}"
        if record.record_id != expected_record_id:
            raise FrontierMismatchError(
                f"frontier record_id mismatch for {key!r}: "
                f"actual={record.record_id!r} expected={expected_record_id!r}"
            )
        bindings = (
            (record.corpus_family.value, entry.corpus_family, "corpus_family"),
            (record.dataset_repo_id, entry.dataset_repo_id, "dataset_repo_id"),
            (record.source_url, entry.source_url, "source_url"),
            (
                record.jurisdiction_or_authority,
                entry.jurisdiction_or_authority,
                "jurisdiction_or_authority",
            ),
        )
        for actual_value, expected_value, field_name in bindings:
            if actual_value != expected_value:
                raise FrontierMismatchError(
                    f"frontier {field_name} mismatch for {key!r}: "
                    f"actual={actual_value!r} expected={expected_value!r}"
                )


@dataclass(frozen=True)
class SourceRightsCatalog:
    schema_version: str
    producer: str
    program_id: str
    task_id: str
    goal_id: str
    evidence_mode: EvidenceMode
    policy_schema_version: str
    sealed_at: str
    authorizing_for_publication: bool
    target_dataset_repo_ids: tuple[str, str]
    artifact_digests: Mapping[str, str]
    expected_scope_frontier_sha256: str
    admitted_record_ids: tuple[str, ...]
    description: str
    currentness_disclaimer: str
    records: tuple[SourceRightsRecord, ...]
    catalog_digest_sha256_value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "program_id": self.program_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "evidence_mode": self.evidence_mode.value,
            "policy_schema_version": self.policy_schema_version,
            "sealed_at": self.sealed_at,
            "authorizing_for_publication": self.authorizing_for_publication,
            "target_dataset_repo_ids": list(self.target_dataset_repo_ids),
            "artifact_digests": dict(self.artifact_digests),
            "expected_scope_frontier_sha256": self.expected_scope_frontier_sha256,
            "admitted_record_ids": list(self.admitted_record_ids),
            "description": self.description,
            "currentness_disclaimer": self.currentness_disclaimer,
            "records": [record.to_dict() for record in self.records],
            "catalog_digest_sha256": self.catalog_digest_sha256_value,
        }

    def catalog_digest_sha256(self) -> str:
        return self.catalog_digest_sha256_value

    @classmethod
    def from_mapping(cls, value: Any, *, context: str = "catalog") -> "SourceRightsCatalog":
        raw = _strict_mapping(value, context)
        artifacts = _load_verifier_artifacts()
        required = (
            "schema_version",
            "producer",
            "program_id",
            "task_id",
            "goal_id",
            "evidence_mode",
            "policy_schema_version",
            "sealed_at",
            "authorizing_for_publication",
            "target_dataset_repo_ids",
            "artifact_digests",
            "expected_scope_frontier_sha256",
            "admitted_record_ids",
            "description",
            "currentness_disclaimer",
            "records",
            "catalog_digest_sha256",
        )
        _exact_keys(raw, required=required, context=context)
        catalog_digest = _strict_sha256(
            raw["catalog_digest_sha256"], f"{context}.catalog_digest_sha256"
        )
        digest_body = dict(raw)
        digest_body.pop("catalog_digest_sha256")
        computed_catalog_digest = sha256_json(digest_body)
        if catalog_digest != computed_catalog_digest:
            raise DigestMismatchError(
                f"{context}.catalog_digest_sha256 mismatch: "
                f"declared={catalog_digest} computed={computed_catalog_digest}"
            )

        exact_identity = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "producer": CATALOG_PRODUCER,
            "program_id": PROGRAM_ID,
            "policy_schema_version": SCHEMA_VERSION,
        }
        identity_values: dict[str, str] = {}
        for key, expected in exact_identity.items():
            actual = _strict_string(raw[key], f"{context}.{key}", maximum=256)
            if actual != expected:
                raise IdentityError(
                    f"{context}.{key} must be exact {expected!r}, got {actual!r}"
                )
            identity_values[key] = actual
        mode = EvidenceMode.parse(raw["evidence_mode"], name=f"{context}.evidence_mode")
        task_id = _strict_string(raw["task_id"], f"{context}.task_id", maximum=32)
        goal_id = _strict_string(raw["goal_id"], f"{context}.goal_id", maximum=32)
        expected_task, expected_goal, _ = _identity_for_mode(mode)
        if task_id != expected_task or goal_id != expected_goal:
            raise IdentityError(
                f"{context} identity tuple must be exactly "
                f"({expected_task!r}, {expected_goal!r}, {mode.value!r})"
            )
        sealed_at = _strict_string(raw["sealed_at"], f"{context}.sealed_at", maximum=40)
        parse_utc_timestamp(sealed_at, name=f"{context}.sealed_at")
        authorizing = _strict_bool(
            raw["authorizing_for_publication"], f"{context}.authorizing_for_publication"
        )
        if mode is EvidenceMode.FIXTURE and authorizing:
            raise IdentityError("fixture catalog can never claim publication authority")
        targets_raw = _strict_list(
            raw["target_dataset_repo_ids"], f"{context}.target_dataset_repo_ids"
        )
        targets = tuple(
            _strict_string(item, f"{context}.target_dataset_repo_ids[{index}]", maximum=128)
            for index, item in enumerate(targets_raw)
        )
        if targets != TARGET_DATASET_REPO_IDS:
            raise IdentityError(
                f"{context}.target_dataset_repo_ids must exactly equal "
                f"{TARGET_DATASET_REPO_IDS!r} in canonical order"
            )
        artifact_digests = _require_artifact_digests_against(
            raw["artifact_digests"],
            expected=artifacts.digests,
            context=f"{context}.artifact_digests",
        )
        expected_frontier_digest = _strict_sha256(
            raw["expected_scope_frontier_sha256"],
            f"{context}.expected_scope_frontier_sha256",
        )
        independently_derived_frontier = artifacts.frontier
        independently_derived_digest = _frontier_digest(independently_derived_frontier)
        if expected_frontier_digest != independently_derived_digest:
            raise FrontierMismatchError(
                f"{context}.expected_scope_frontier_sha256 is not the independently derived digest"
            )
        if artifact_digests["expected_scope_frontier_sha256"] != expected_frontier_digest:
            raise FrontierMismatchError(
                f"{context} frontier digest bindings disagree"
            )
        registry = artifacts.registry
        records_raw = _strict_list(raw["records"], f"{context}.records")
        if not records_raw:
            raise CatalogSchemaError(f"{context}.records must not be empty")
        records = tuple(
            SourceRightsRecord.from_mapping(
                item,
                context=f"{context}.records[{index}]",
                evidence_mode=mode,
                registry=registry,
            )
            for index, item in enumerate(records_raw)
        )
        record_ids = [record.record_id for record in records]
        if len(record_ids) != len(set(record_ids)):
            raise CatalogSchemaError(f"{context}.record_id values must be unique")
        _assert_records_match_frontier(records, independently_derived_frontier)
        admitted_raw = _strict_list(
            raw["admitted_record_ids"], f"{context}.admitted_record_ids"
        )
        admitted_ids = tuple(
            _strict_identifier(item, f"{context}.admitted_record_ids[{index}]")
            for index, item in enumerate(admitted_raw)
        )
        if len(admitted_ids) != len(set(admitted_ids)):
            raise CatalogSchemaError(f"{context}.admitted_record_ids must be unique")
        if not set(admitted_ids).issubset(record_ids):
            raise CatalogSchemaError(f"{context}.admitted_record_ids contains unknown records")
        description = _strict_string(raw["description"], f"{context}.description", maximum=4096)
        disclaimer = _strict_string(
            raw["currentness_disclaimer"],
            f"{context}.currentness_disclaimer",
            maximum=4096,
        )
        return cls(
            schema_version=identity_values["schema_version"],
            producer=identity_values["producer"],
            program_id=identity_values["program_id"],
            task_id=task_id,
            goal_id=goal_id,
            evidence_mode=mode,
            policy_schema_version=identity_values["policy_schema_version"],
            sealed_at=sealed_at,
            authorizing_for_publication=authorizing,
            target_dataset_repo_ids=(targets[0], targets[1]),
            artifact_digests=artifact_digests,
            expected_scope_frontier_sha256=expected_frontier_digest,
            admitted_record_ids=admitted_ids,
            description=description,
            currentness_disclaimer=disclaimer,
            records=records,
            catalog_digest_sha256_value=catalog_digest,
        )


# ---------------------------------------------------------------------------
# One evaluator for every public selector and authorization gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    authorizing: bool
    record_id: str
    source_id: str
    content_scope: str
    rights_disposition: str
    reason_codes: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "authorizing": self.authorizing,
            "record_id": self.record_id,
            "source_id": self.source_id,
            "content_scope": self.content_scope,
            "rights_disposition": self.rights_disposition,
            "reason_codes": list(self.reason_codes),
            "message": self.message,
        }


def _decision(
    record: SourceRightsRecord,
    *,
    admitted: bool,
    reason_codes: Sequence[str],
    message: str,
) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=admitted,
        authorizing=False,
        record_id=record.record_id,
        source_id=record.source_id,
        content_scope=record.content_scope.value,
        rights_disposition=record.rights_disposition.value,
        reason_codes=tuple(reason_codes),
        message=message,
    )


def _freshness_denial(label: str, value: str, verifier_now: datetime) -> tuple[str, str] | None:
    timestamp = parse_utc_timestamp(value, name=label)
    if timestamp > verifier_now:
        return "future_timestamp", f"{label} is after verifier-owned time (zero future skew)"
    if timestamp < verifier_now - MAX_EVIDENCE_AGE:
        return "stale_evidence", f"{label} is older than the immutable 90-day maximum"
    return None


def _evaluate_record_at(
    record: SourceRightsRecord,
    *,
    catalog: SourceRightsCatalog,
    verifier_now: datetime,
) -> AdmissionDecision:
    terms_at = parse_utc_timestamp(record.terms.verifier_observed_at, name="terms.verifier_observed_at")
    robots_at = parse_utc_timestamp(record.robots.verifier_observed_at, name="robots.verifier_observed_at")
    reviewed_at = parse_utc_timestamp(record.reviewed_at, name="reviewed_at")
    record_sealed_at = parse_utc_timestamp(record.sealed_at, name="record.sealed_at")
    catalog_sealed_at = parse_utc_timestamp(catalog.sealed_at, name="catalog.sealed_at")
    temporal_values: list[tuple[str, str]] = [
        ("terms.verifier_observed_at", record.terms.verifier_observed_at),
        ("robots.verifier_observed_at", record.robots.verifier_observed_at),
        ("reviewed_at", record.reviewed_at),
        ("record.sealed_at", record.sealed_at),
        ("catalog.sealed_at", catalog.sealed_at),
    ]
    for receipt in record.condition_evidence:
        temporal_values.append(
            (
                f"condition_evidence[{receipt.condition_id}].verifier_observed_at",
                receipt.verifier_observed_at,
            )
        )
    for label, value in temporal_values:
        denial = _freshness_denial(label, value, verifier_now)
        if denial is not None:
            return _decision(
                record,
                admitted=False,
                reason_codes=(denial[0], label),
                message=denial[1],
            )
    if terms_at > reviewed_at:
        return _decision(
            record,
            admitted=False,
            reason_codes=("terms_after_review",),
            message="terms evidence was observed after review",
        )
    if robots_at > reviewed_at:
        return _decision(
            record,
            admitted=False,
            reason_codes=("robots_after_review",),
            message="robots evidence was observed after review",
        )
    for receipt in record.condition_evidence:
        observed = parse_utc_timestamp(
            receipt.verifier_observed_at,
            name=f"condition_evidence[{receipt.condition_id}].verifier_observed_at",
        )
        if observed > reviewed_at:
            return _decision(
                record,
                admitted=False,
                reason_codes=("condition_evidence_after_review", receipt.condition_id),
                message="conditional evidence was observed after review",
            )
    if reviewed_at > record_sealed_at:
        return _decision(
            record,
            admitted=False,
            reason_codes=("review_after_record_seal",),
            message="reviewed_at is after record.sealed_at",
        )
    if record_sealed_at > catalog_sealed_at:
        return _decision(
            record,
            admitted=False,
            reason_codes=("record_after_catalog_seal",),
            message="record.sealed_at is after catalog.sealed_at",
        )

    if record.content_scope in DEFAULT_QUARANTINED_CONTENT_SCOPES:
        return _decision(
            record,
            admitted=False,
            reason_codes=("out_of_release_scope", record.content_scope.value),
            message="presentation, annotation, editorial, and database layers are excluded",
        )
    if record.content_scope not in ADMISSIBLE_CONTENT_SCOPES:
        return _decision(
            record,
            admitted=False,
            reason_codes=("unsupported_content_scope",),
            message="content scope is unsupported",
        )
    if record.rights_disposition not in {
        RightsDisposition.ALLOWED,
        RightsDisposition.CONDITIONAL,
    }:
        return _decision(
            record,
            admitted=False,
            reason_codes=(f"rights_{record.rights_disposition.value}",),
            message="rights disposition does not permit release",
        )
    if not record.legal_basis.supports_admission:
        return _decision(
            record,
            admitted=False,
            reason_codes=("legal_basis_not_admissible",),
            message="legal basis does not support release admission",
        )
    if not record.permissions.all_required_granted():
        missing = tuple(
            name
            for name, allowed in (
                ("redistribution", record.permissions.redistribution),
                ("derivatives", record.permissions.derivatives),
                ("archive", record.permissions.archive),
            )
            if not allowed
        )
        return _decision(
            record,
            admitted=False,
            reason_codes=("permissions_incomplete", *missing),
            message="redistribution, derivative-work, and archival permissions are all required",
        )
    robots = record.robots_access_disposition
    if robots in {
        RobotsAccessDisposition.DENIED,
        RobotsAccessDisposition.UNKNOWN,
        RobotsAccessDisposition.UNAVAILABLE,
    }:
        return _decision(
            record,
            admitted=False,
            reason_codes=(f"robots_{robots.value}",),
            message="robots/access evidence does not permit acquisition",
        )
    conditional = (
        record.rights_disposition is RightsDisposition.CONDITIONAL
        or robots is RobotsAccessDisposition.CONDITIONAL
    )
    receipt_ids = tuple(item.condition_id for item in record.condition_evidence)
    if conditional:
        if not record.access_conditions:
            return _decision(
                record,
                admitted=False,
                reason_codes=("conditional_without_requirements",),
                message="conditional admission requires explicit acquisition requirements",
            )
        if receipt_ids != record.access_conditions:
            return _decision(
                record,
                admitted=False,
                reason_codes=("conditional_evidence_set_mismatch",),
                message="every and only required condition must have one content-addressed receipt",
            )
    elif record.access_conditions or record.condition_evidence:
        return _decision(
            record,
            admitted=False,
            reason_codes=("unexpected_conditional_evidence",),
            message="unconditional records must not carry caller-selectable condition evidence",
        )
    if record.review_status is not ReviewStatus.REVIEWED:
        return _decision(
            record,
            admitted=False,
            reason_codes=(f"review_{record.review_status.value}",),
            message="record is not currently reviewed",
        )
    if record.attribution_notice == "":
        return _decision(
            record,
            admitted=False,
            reason_codes=("missing_attribution",),
            message="attribution notice is required",
        )
    reasons = ["admitted", "all_operations_permitted", "evidence_current"]
    if conditional:
        reasons.append("conditional_evidence_verified")
    return _decision(
        record,
        admitted=True,
        reason_codes=reasons,
        message="record admitted by the complete source-rights evaluator",
    )


_LIVE_AUTHORIZATION_CAPABILITY = object()


def _validated_catalog(value: SourceRightsCatalog | JsonMapping) -> SourceRightsCatalog:
    if isinstance(value, SourceRightsCatalog):
        # Reparse even frozen/directly constructed instances; constructors are not authority.
        return SourceRightsCatalog.from_mapping(value.to_dict(), context="catalog")
    if isinstance(value, Mapping):
        return SourceRightsCatalog.from_mapping(value, context="catalog")
    raise CatalogSchemaError("a complete legal-source-rights-catalog-v2 object is required")


def _evaluate_catalog_at(
    catalog: SourceRightsCatalog,
    *,
    verifier_now: datetime,
    authorization_capability: object | None = None,
) -> dict[str, Any]:
    if type(verifier_now) is not datetime or verifier_now.tzinfo is None:
        raise CatalogSchemaError("verifier-owned clock must be an aware datetime")
    verifier_now = verifier_now.astimezone(timezone.utc)
    decisions = tuple(
        _evaluate_record_at(record, catalog=catalog, verifier_now=verifier_now)
        for record in catalog.records
    )
    admitted_ids = tuple(item.record_id for item in decisions if item.admitted)
    if admitted_ids != catalog.admitted_record_ids:
        raise RightsAdmissionError(
            "catalog admitted_record_ids must exactly equal evaluator admission for every "
            f"expected record; declared={catalog.admitted_record_ids!r} actual={admitted_ids!r}"
        )
    denied_in_scope = tuple(
        item.record_id
        for item in decisions
        if not item.admitted
        and ContentScope(item.content_scope) in ADMISSIBLE_CONTENT_SCOPES
    )
    catalog_authorized = bool(
        authorization_capability is _LIVE_AUTHORIZATION_CAPABILITY
        and catalog.evidence_mode is EvidenceMode.LIVE
        and catalog.authorizing_for_publication
        and not denied_in_scope
        and admitted_ids
    )
    if catalog.evidence_mode is EvidenceMode.FIXTURE:
        catalog_authorized = False
    if catalog_authorized:
        decisions = tuple(
            replace(item, authorizing=True) if item.admitted else item for item in decisions
        )
    denied = tuple(item for item in decisions if not item.admitted)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_schema_version": catalog.schema_version,
        "producer": catalog.producer,
        "program_id": catalog.program_id,
        "task_id": catalog.task_id,
        "goal_id": catalog.goal_id,
        "evidence_mode": catalog.evidence_mode.value,
        "verified_at": format_utc_timestamp(verifier_now),
        "authorizing_for_publication": catalog_authorized,
        "fixture_only_non_authorizing": catalog.evidence_mode is EvidenceMode.FIXTURE,
        "authority_suppressed": bool(denied_in_scope),
        "denied_in_scope_record_ids": list(denied_in_scope),
        "record_count": len(catalog.records),
        "expected_frontier_count": EXPECTED_FRONTIER_SIZE,
        "admitted_count": len(admitted_ids),
        "denied_count": len(denied),
        "admitted_record_ids": list(admitted_ids),
        "denied_record_ids": [item.record_id for item in denied],
        "catalog_digest_sha256": catalog.catalog_digest_sha256(),
        "expected_scope_frontier_sha256": catalog.expected_scope_frontier_sha256,
        "artifact_digests": dict(catalog.artifact_digests),
        "decisions": [item.to_dict() for item in decisions],
        "currentness_disclaimer": catalog.currentness_disclaimer,
    }


def _verifier_now_for(catalog: SourceRightsCatalog) -> datetime:
    if catalog.evidence_mode is EvidenceMode.FIXTURE:
        return fixture_verifier_now()
    return datetime.now(timezone.utc)


def evaluate_catalog(value: SourceRightsCatalog | JsonMapping) -> dict[str, Any]:
    """Evaluate a complete catalog non-authoritatively with a verifier-owned clock."""

    catalog = _validated_catalog(value)
    return _evaluate_catalog_at(catalog, verifier_now=_verifier_now_for(catalog))


def evaluate_scope_rights(
    value: SourceRightsCatalog | JsonMapping,
    record_id: str,
) -> AdmissionDecision:
    """Return one record decision after evaluating the complete expected catalog."""

    requested = _strict_identifier(record_id, "record_id")
    report = evaluate_catalog(value)
    for raw in report["decisions"]:
        if raw["record_id"] == requested:
            return AdmissionDecision(
                admitted=raw["admitted"],
                authorizing=raw["authorizing"],
                record_id=raw["record_id"],
                source_id=raw["source_id"],
                content_scope=raw["content_scope"],
                rights_disposition=raw["rights_disposition"],
                reason_codes=tuple(raw["reason_codes"]),
                message=raw["message"],
            )
    raise CatalogSchemaError(f"unknown record_id: {requested!r}")


def require_scope_rights(
    value: SourceRightsCatalog | JsonMapping,
    record_id: str,
) -> AdmissionDecision:
    decision = evaluate_scope_rights(value, record_id)
    if not decision.admitted:
        raise RightsAdmissionError(
            f"rights admission denied ({','.join(decision.reason_codes)}): {decision.message}"
        )
    return decision


def admitted_records(
    value: SourceRightsCatalog | JsonMapping,
) -> tuple[SourceRightsRecord, ...]:
    """Select admitted records only after the same evaluator considered all records."""

    catalog = _validated_catalog(value)
    report = _evaluate_catalog_at(catalog, verifier_now=_verifier_now_for(catalog))
    admitted = set(report["admitted_record_ids"])
    return tuple(record for record in catalog.records if record.record_id in admitted)


def assert_catalog_distinguishes_scopes(catalog: SourceRightsCatalog | JsonMapping) -> None:
    parsed = _validated_catalog(catalog)
    scopes = {record.content_scope for record in parsed.records}
    required = set(ContentScope)
    if scopes != required:
        raise CatalogSchemaError(
            f"catalog must distinguish every content scope; missing={sorted(s.value for s in required-scopes)!r}"
        )


# ---------------------------------------------------------------------------
# Fixed-path loaders, schema validation, and audits
# ---------------------------------------------------------------------------


def _load_catalog_payload(path: Path) -> dict[str, Any]:
    raw_bytes = _read_regular_file_once(path, context="source-rights catalog")
    value = _strict_json_loads(raw_bytes, context="source-rights catalog")
    if type(value) is not dict:
        raise CatalogSchemaError("source-rights catalog root must be an object")
    return value


def load_catalog_snapshot() -> tuple[bytes, dict[str, Any]]:
    """Single-read the exact canonical fixture bytes and strict JSON object."""

    raw_bytes = _read_regular_file_once(
        default_fixture_catalog_path(), context="source-rights catalog"
    )
    value = _strict_json_loads(raw_bytes, context="source-rights catalog")
    if type(value) is not dict:
        raise CatalogSchemaError("source-rights catalog root must be an object")
    return raw_bytes, value


def load_catalog_payload() -> dict[str, Any]:
    """Load only the canonical fixture path; arbitrary catalog paths are not accepted."""

    return load_catalog_snapshot()[1]


def load_source_rights_catalog() -> SourceRightsCatalog:
    return SourceRightsCatalog.from_mapping(load_catalog_payload())


def get_fixture_source_rights_catalog() -> SourceRightsCatalog:
    # Intentionally uncached so byte changes cannot survive parsing/evaluation.
    return load_source_rights_catalog()


def clear_catalog_cache() -> None:
    return None


def load_schema_document() -> dict[str, Any]:
    path = default_schema_path()
    raw_bytes = _read_regular_file_once(path, context="canonical source-rights schema")
    value = _strict_json_loads(raw_bytes, context="canonical source-rights schema")
    if type(value) is not dict:
        raise CatalogSchemaError("source-rights schema root must be an object")
    return value


def validate_catalog_against_schema(value: JsonMapping) -> list[str]:
    errors: list[str] = []
    schema = load_schema_document()
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return ["jsonschema is required for authoritative catalog validation"]
    try:
        validator = jsonschema.Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
            path = ".".join(str(item) for item in error.absolute_path) or "<root>"
            errors.append(f"{path}: {error.message}")
    except Exception as exc:  # pragma: no cover - dependency-specific
        errors.append(f"jsonschema validation failed closed: {exc}")
    if errors:
        return errors
    try:
        SourceRightsCatalog.from_mapping(value)
    except LegalSourceRightsPolicyError as exc:
        errors.append(str(exc))
    return errors


def build_fixture_compliance_projection(
    catalog: SourceRightsCatalog | JsonMapping | None = None,
) -> dict[str, Any]:
    value = catalog if catalog is not None else get_fixture_source_rights_catalog()
    parsed = _validated_catalog(value)
    if parsed.evidence_mode is not EvidenceMode.FIXTURE:
        raise IdentityError("fixture projection requires the exact fixture identity tuple")
    report = _evaluate_catalog_at(parsed, verifier_now=_verifier_now_for(parsed))
    report["mode"] = "fixture_only"
    report["authorizing_for_publication"] = False
    report["fixture_only_non_authorizing"] = True
    return report


def audit_fixture_catalog(payload: JsonMapping | None = None) -> dict[str, Any]:
    """Audit one fixed-path fixture read or an already single-read fixture mapping."""

    payload = load_catalog_payload() if payload is None else payload
    if type(payload) is not dict:
        raise CatalogSchemaError("fixture catalog must be an exact JSON object")
    errors = validate_catalog_against_schema(payload)
    if errors:
        raise CatalogSchemaError("fixture catalog validation failed:\n- " + "\n- ".join(errors))
    catalog = SourceRightsCatalog.from_mapping(payload)
    assert_catalog_distinguishes_scopes(catalog)
    report = build_fixture_compliance_projection(catalog)
    report["status"] = "passed"
    report["catalog_path"] = _FIXTURE_RELATIVE_PATH.as_posix()
    report["schema_path"] = _SCHEMA_RELATIVE_PATH.as_posix()
    report["spdx_registry_path"] = _SPDX_RELATIVE_PATH.as_posix()
    if report["record_count"] != EXPECTED_FRONTIER_SIZE:
        raise FrontierMismatchError("fixture does not cover the complete expected frontier")
    if report["admitted_count"] < EXPECTED_STATE_SOURCE_COUNT + 1:
        raise RightsAdmissionError("fixture must admit all state sources and Federal government text")
    report["authorizing_for_publication"] = False
    report["fixture_only_non_authorizing"] = True
    return report


def require_live_source_evidence() -> dict[str, Any]:
    """Authorize only the canonical live catalog using the verifier's system clock."""

    path = default_live_catalog_path()
    if not path.is_file():
        raise LiveEvidenceRequiredError(
            "canonical live source-rights catalog is missing; LCR-078 must seal it"
        )
    payload = _load_catalog_payload(path)
    errors = validate_catalog_against_schema(payload)
    if errors:
        raise LiveEvidenceRequiredError("live catalog validation failed:\n- " + "\n- ".join(errors))
    catalog = SourceRightsCatalog.from_mapping(payload)
    if catalog.evidence_mode is not EvidenceMode.LIVE:
        raise LiveEvidenceRequiredError("canonical live catalog has the wrong identity tuple")
    report = _evaluate_catalog_at(
        catalog,
        verifier_now=datetime.now(timezone.utc),
        authorization_capability=_LIVE_AUTHORIZATION_CAPABILITY,
    )
    if not report["authorizing_for_publication"]:
        raise LiveEvidenceRequiredError(
            "live source-rights catalog is not authoritative; denied in-scope records="
            f"{report['denied_in_scope_record_ids']!r}"
        )
    report["status"] = "passed"
    report["mode"] = "live"
    return report


__all__ = [
    "ADMISSIBLE_CONTENT_SCOPES",
    "CATALOG_PRODUCER",
    "CATALOG_SCHEMA_VERSION",
    "CANONICAL_LICENSE_REF_DIGESTS",
    "CANONICAL_LCR002_SHA256",
    "CANONICAL_LCR048_SHA256",
    "CANONICAL_SPDX_ACTIVE_IDS_SHA256",
    "CANONICAL_SPDX_DEPRECATED_IDS_SHA256",
    "CANONICAL_SPDX_PACKAGE_SHA256",
    "CONDITION_EVIDENCE_SCHEMA_VERSION",
    "CURRENTNESS_DISCLAIMER",
    "DEFAULT_MAX_EVIDENCE_AGE",
    "DEFAULT_MAX_FUTURE_SKEW",
    "DEFAULT_QUARANTINED_CONTENT_SCOPES",
    "EVIDENCE_SCHEMA_VERSION",
    "EXPECTED_FRONTIER_SIZE",
    "EXPECTED_STATE_SOURCE_COUNT",
    "FEDERAL_DATASET_REPO_ID",
    "FIXTURE_GOAL_ID",
    "FIXTURE_TASK_ID",
    "FIXTURE_VERIFIER_CLOCK_UTC",
    "GOAL_ID",
    "LIVE_GOAL_ID",
    "LIVE_TASK_ID",
    "MAX_EVIDENCE_AGE",
    "MAX_FUTURE_SKEW",
    "PROGRAM_ID",
    "PRODUCER",
    "SCHEMA_VERSION",
    "SPDX_REGISTRY_SCHEMA_VERSION",
    "STATE_DATASET_REPO_ID",
    "TARGET_DATASET_REPO_IDS",
    "TASK_ID",
    "VERIFIER_ID",
    "AdmissionDecision",
    "CardOnlyEvidenceError",
    "CatalogSchemaError",
    "ConditionEvidence",
    "ContentScope",
    "CorpusFamily",
    "DigestMismatchError",
    "EvidenceArtifact",
    "EvidenceMode",
    "FrontierMismatchError",
    "IdentityError",
    "LegalBasis",
    "LegalSourceRightsPolicyError",
    "LicenseIdentityError",
    "LicenseRefDefinition",
    "LiveEvidenceRequiredError",
    "Permissions",
    "ProhibitedScopeError",
    "RightsAdmissionError",
    "RightsDisposition",
    "RobotsAccessDisposition",
    "ReviewStatus",
    "ScopeFrontierEntry",
    "ScopeMismatchError",
    "SourceRightsCatalog",
    "SourceRightsRecord",
    "SpdxLicenseRegistry",
    "StaleEvidenceError",
    "UnknownRightsError",
    "admitted_records",
    "assert_catalog_distinguishes_scopes",
    "audit_fixture_catalog",
    "build_fixture_compliance_projection",
    "canonical_json",
    "clear_catalog_cache",
    "clear_spdx_registry_cache",
    "compute_artifact_digests",
    "default_federal_baseline_path",
    "default_fixture_catalog_path",
    "default_live_catalog_path",
    "default_policy_module_path",
    "default_schema_path",
    "default_spdx_registry_path",
    "default_state_source_catalog_path",
    "derive_expected_scope_frontier",
    "evaluate_catalog",
    "evaluate_scope_rights",
    "fixture_verifier_now",
    "format_utc_timestamp",
    "frontier_digest_sha256",
    "get_fixture_source_rights_catalog",
    "get_spdx_registry",
    "is_licenseref",
    "load_catalog_payload",
    "load_catalog_snapshot",
    "load_schema_document",
    "load_source_rights_catalog",
    "load_spdx_registry",
    "normalize_spdx",
    "parse_utc_timestamp",
    "repository_root",
    "require_artifact_digests",
    "require_live_source_evidence",
    "require_scope_rights",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
    "sha256_text",
    "validate_catalog_against_schema",
]
