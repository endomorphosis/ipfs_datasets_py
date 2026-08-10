"""Cross-corpus source-rights and redistribution admission contract (LCR-077).

Source authority is **not** redistribution authority. Every admitted source and
content scope must carry current, evidence-backed rights status before it can
enter either public legal corpus (state laws or Federal Register).

Design invariants
-----------------
* Government / statutory text is distinguished from site presentation,
  annotations, editorial enhancements, and database content.
* SPDX or LicenseRef identity is required; a dataset-card ``license:`` label
  alone never proves admissibility.
* Terms URL, observed-at timestamp, and content digest are required.
* Attribution / notice duties, redistribution / derivative / archive
  permissions, robots/access evidence, legal basis, and review state are
  required for every scope.
* Unknown, prohibited, stale, unreviewed, scope-mismatched, unsupported, or
  malformed evidence fails closed (deny-on-unknown).
* Live network I/O is out of scope; fixture and offline catalogs only.
* Fixture-only success is explicitly non-authorizing for publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-source-rights-policy-v1"
CATALOG_SCHEMA_VERSION: Final = "legal-source-rights-catalog-v1"
TASK_ID: Final = "LCR-077"
GOAL_ID: Final = "LCR-G141"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "legal_source_rights_policy.py"

DEFAULT_SCHEMA_RELATIVE_PATH: Final = Path("data/legal/legal_source_rights_catalog.schema.json")
DEFAULT_FIXTURE_CATALOG_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/legal_source_rights_catalog.json"
)
DEFAULT_LIVE_CATALOG_RELATIVE_PATH: Final = Path("data/legal/legal_source_rights_catalog.json")
DEFAULT_COMPLIANCE_RECEIPT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)

STATE_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
FEDERAL_DATASET_REPO_ID: Final = "justicedao/ipfs_federal_register"
TARGET_DATASET_REPO_IDS: Final = frozenset(
    {STATE_DATASET_REPO_ID, FEDERAL_DATASET_REPO_ID}
)

# Fixed non-authorizing verifier clock for fixture-only evaluation (LCR-077).
# Live mode (LCR-078+) must supply a trusted clock; the catalog never sets time.
FIXTURE_VERIFIER_CLOCK_UTC: Final = "2026-08-10T12:00:00Z"

# Evidence older than this relative to the trusted verifier clock is stale.
DEFAULT_MAX_EVIDENCE_AGE: Final = timedelta(days=90)
# Bounded skew: observed_at may not be more than this ahead of verifier time.
DEFAULT_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)

CURRENTNESS_DISCLAIMER: Final = (
    "Terms, robots, and rights observation timestamps record when evidence was "
    "captured; they are not a claim that the underlying law is legally current "
    "as of wall-clock time. Fixture-only success is non-authorizing for "
    "publication. Source authority is not redistribution authority."
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
ClockFn = Callable[[], datetime]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
# Exact SPDX short-form identifiers or LicenseRef-* custom identifiers.
# LCR-082 will bind these to a vendored registry; LCR-077 accepts the shape
# and a closed allow-list of known identifiers used by the fixture catalog.
_SPDX_ID_RE = re.compile(
    r"^(?:"
    r"CC0-1\.0|CC-BY-4\.0|CC-BY-SA-4\.0|MIT|Apache-2\.0|BSD-2-Clause|BSD-3-Clause|"
    r"GPL-3\.0-only|GPL-3\.0-or-later|LGPL-3\.0-only|"
    r"LicenseRef-[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}"
    r")$"
)
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalSourceRightsPolicyError(ValueError):
    """Base error for source-rights policy failures."""

    code: str = "legal_source_rights_policy_error"


class CatalogSchemaError(LegalSourceRightsPolicyError):
    """Raised when the rights catalog is missing or malformed."""

    code = "catalog_schema_error"


class RightsAdmissionError(LegalSourceRightsPolicyError):
    """Raised when a scope cannot be admitted under deny-on-unknown rules."""

    code = "rights_admission_error"


class StaleEvidenceError(RightsAdmissionError):
    """Raised when terms/robots/review evidence is outside trusted freshness bounds."""

    code = "stale_evidence_error"


class ScopeMismatchError(RightsAdmissionError):
    """Raised when a requested content scope does not match the record."""

    code = "scope_mismatch_error"


class ProhibitedScopeError(RightsAdmissionError):
    """Raised when redistribution is prohibited for the content scope."""

    code = "prohibited_scope_error"


class UnknownRightsError(RightsAdmissionError):
    """Raised when rights status is unknown or unsupported."""

    code = "unknown_rights_error"


class CardOnlyEvidenceError(RightsAdmissionError):
    """Raised when only a dataset-card license label is offered as evidence."""

    code = "card_only_evidence_error"


class LiveEvidenceRequiredError(LegalSourceRightsPolicyError):
    """Raised when live source evidence is required but unavailable."""

    code = "live_evidence_required_error"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CorpusFamily(str, Enum):
    """Target corpus family for a rights record."""

    STATE_LAWS = "state_laws"
    FEDERAL_REGISTER = "federal_register"

    @classmethod
    def coerce(cls, value: Any) -> "CorpusFamily":
        if isinstance(value, CorpusFamily):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "state": cls.STATE_LAWS,
            "states": cls.STATE_LAWS,
            "ipfs_state_laws": cls.STATE_LAWS,
            "justicedao/ipfs_state_laws": cls.STATE_LAWS,
            "federal": cls.FEDERAL_REGISTER,
            "fr": cls.FEDERAL_REGISTER,
            "federal_register": cls.FEDERAL_REGISTER,
            "ipfs_federal_register": cls.FEDERAL_REGISTER,
            "justicedao/ipfs_federal_register": cls.FEDERAL_REGISTER,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown corpus family: {value!r}")

    @property
    def dataset_repo_id(self) -> str:
        if self is CorpusFamily.STATE_LAWS:
            return STATE_DATASET_REPO_ID
        return FEDERAL_DATASET_REPO_ID


class ContentScope(str, Enum):
    """Content scope that must be rights-evaluated independently of the host site."""

    STATUTORY_TEXT = "statutory_text"
    FEDERAL_GOVERNMENT_TEXT = "federal_government_text"
    SITE_PRESENTATION = "site_presentation"
    ANNOTATIONS = "annotations"
    EDITORIAL_ENHANCEMENTS = "editorial_enhancements"
    DATABASE_CONTENT = "database_content"

    @classmethod
    def coerce(cls, value: Any) -> "ContentScope":
        if isinstance(value, ContentScope):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "statute": cls.STATUTORY_TEXT,
            "statutes": cls.STATUTORY_TEXT,
            "statute_text": cls.STATUTORY_TEXT,
            "code_text": cls.STATUTORY_TEXT,
            "government_text": cls.FEDERAL_GOVERNMENT_TEXT,
            "federal_text": cls.FEDERAL_GOVERNMENT_TEXT,
            "fr_text": cls.FEDERAL_GOVERNMENT_TEXT,
            "us_government_work": cls.FEDERAL_GOVERNMENT_TEXT,
            "presentation": cls.SITE_PRESENTATION,
            "layout": cls.SITE_PRESENTATION,
            "chrome": cls.SITE_PRESENTATION,
            "ui": cls.SITE_PRESENTATION,
            "annotation": cls.ANNOTATIONS,
            "headnotes": cls.ANNOTATIONS,
            "editorial": cls.EDITORIAL_ENHANCEMENTS,
            "editorial_content": cls.EDITORIAL_ENHANCEMENTS,
            "enhancements": cls.EDITORIAL_ENHANCEMENTS,
            "database": cls.DATABASE_CONTENT,
            "db": cls.DATABASE_CONTENT,
            "selection_arrangement": cls.DATABASE_CONTENT,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown content scope: {value!r}")

    @property
    def is_government_or_statutory_text(self) -> bool:
        return self in {
            ContentScope.STATUTORY_TEXT,
            ContentScope.FEDERAL_GOVERNMENT_TEXT,
        }

    @property
    def is_presentation_or_enhancement(self) -> bool:
        return self in {
            ContentScope.SITE_PRESENTATION,
            ContentScope.ANNOTATIONS,
            ContentScope.EDITORIAL_ENHANCEMENTS,
            ContentScope.DATABASE_CONTENT,
        }


# Content scopes that may enter the default public release when fully evidenced.
ADMISSIBLE_CONTENT_SCOPES: Final = frozenset(
    {
        ContentScope.STATUTORY_TEXT,
        ContentScope.FEDERAL_GOVERNMENT_TEXT,
    }
)

# Content scopes that are never admitted into the default release under LCR-077.
DEFAULT_QUARANTINED_CONTENT_SCOPES: Final = frozenset(
    {
        ContentScope.SITE_PRESENTATION,
        ContentScope.ANNOTATIONS,
        ContentScope.EDITORIAL_ENHANCEMENTS,
        ContentScope.DATABASE_CONTENT,
    }
)


class RightsDisposition(str, Enum):
    """Redistribution disposition for one source/content-scope pair."""

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"

    @classmethod
    def coerce(cls, value: Any) -> "RightsDisposition":
        if isinstance(value, RightsDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "permit": cls.ALLOWED,
            "permitted": cls.ALLOWED,
            "admit": cls.ALLOWED,
            "admitted": cls.ALLOWED,
            "deny": cls.PROHIBITED,
            "denied": cls.PROHIBITED,
            "forbidden": cls.PROHIBITED,
            "block": cls.PROHIBITED,
            "blocked": cls.PROHIBITED,
            "unreviewed": cls.UNKNOWN,
            "not_reviewed": cls.UNKNOWN,
            "n/a": cls.UNSUPPORTED,
            "na": cls.UNSUPPORTED,
            "not_supported": cls.UNSUPPORTED,
            "hold": cls.QUARANTINED,
            "hold_out": cls.QUARANTINED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown rights disposition: {value!r}")

    @property
    def may_enter_default_release(self) -> bool:
        return self is RightsDisposition.ALLOWED


class RobotsAccessDisposition(str, Enum):
    """Robots / access disposition recorded for the source."""

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    DENIED = "denied"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"

    @classmethod
    def coerce(cls, value: Any) -> "RobotsAccessDisposition":
        if isinstance(value, RobotsAccessDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "allow": cls.ALLOWED,
            "permit": cls.ALLOWED,
            "permitted": cls.ALLOWED,
            "deny": cls.DENIED,
            "denied": cls.DENIED,
            "block": cls.DENIED,
            "blocked": cls.DENIED,
            "disallow": cls.DENIED,
            "missing": cls.UNAVAILABLE,
            "none": cls.UNAVAILABLE,
            "n/a": cls.UNAVAILABLE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown robots access disposition: {value!r}")

    @property
    def permits_acquisition(self) -> bool:
        # Conditional requires fully modeled conditions (checked by evaluator).
        return self in {
            RobotsAccessDisposition.ALLOWED,
            RobotsAccessDisposition.CONDITIONAL,
        }


class ReviewStatus(str, Enum):
    """Human / policy review state for a rights record."""

    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @classmethod
    def coerce(cls, value: Any) -> "ReviewStatus":
        if isinstance(value, ReviewStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "ok": cls.REVIEWED,
            "pass": cls.REVIEWED,
            "passed": cls.REVIEWED,
            "approved": cls.REVIEWED,
            "pending": cls.UNREVIEWED,
            "todo": cls.UNREVIEWED,
            "fail": cls.REJECTED,
            "failed": cls.REJECTED,
            "denied": cls.REJECTED,
            "stale": cls.EXPIRED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown review status: {value!r}")


class LegalBasis(str, Enum):
    """Legal basis supporting redistribution of the content scope."""

    US_GOVERNMENT_WORK = "us_government_work"
    GOVERNMENT_EDICTS_DOCTRINE = "government_edicts_doctrine"
    PUBLIC_DOMAIN = "public_domain"
    EXPLICIT_LICENSE = "explicit_license"
    STATUTORY_PERMISSION = "statutory_permission"
    UNKNOWN = "unknown"
    PROPRIETARY = "proprietary"
    NOT_APPLICABLE = "not_applicable"

    @classmethod
    def coerce(cls, value: Any) -> "LegalBasis":
        if isinstance(value, LegalBasis):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "us_gov": cls.US_GOVERNMENT_WORK,
            "us_government": cls.US_GOVERNMENT_WORK,
            "17_usc_105": cls.US_GOVERNMENT_WORK,
            "government_edicts": cls.GOVERNMENT_EDICTS_DOCTRINE,
            "edicts": cls.GOVERNMENT_EDICTS_DOCTRINE,
            "pd": cls.PUBLIC_DOMAIN,
            "publicdomain": cls.PUBLIC_DOMAIN,
            "license": cls.EXPLICIT_LICENSE,
            "spdx": cls.EXPLICIT_LICENSE,
            "statute": cls.STATUTORY_PERMISSION,
            "statute_permission": cls.STATUTORY_PERMISSION,
            "copyrighted": cls.PROPRIETARY,
            "all_rights_reserved": cls.PROPRIETARY,
            "n/a": cls.NOT_APPLICABLE,
            "na": cls.NOT_APPLICABLE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown legal basis: {value!r}")

    @property
    def supports_default_admission(self) -> bool:
        return self in {
            LegalBasis.US_GOVERNMENT_WORK,
            LegalBasis.GOVERNMENT_EDICTS_DOCTRINE,
            LegalBasis.PUBLIC_DOMAIN,
            LegalBasis.EXPLICIT_LICENSE,
            LegalBasis.STATUTORY_PERMISSION,
        }


class EvidenceMode(str, Enum):
    """Whether a catalog is fixture-only (non-authorizing) or live evidence."""

    FIXTURE = "fixture"
    LIVE = "live"

    @classmethod
    def coerce(cls, value: Any) -> "EvidenceMode":
        if isinstance(value, EvidenceMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "fixture_only": cls.FIXTURE,
            "offline": cls.FIXTURE,
            "test": cls.FIXTURE,
            "sealed": cls.FIXTURE,
            "production": cls.LIVE,
            "authorizing": cls.LIVE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise CatalogSchemaError(f"unknown evidence mode: {value!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    """Return the repository root that contains ``data/legal``."""

    return Path(__file__).resolve().parents[3]


def default_schema_path() -> Path:
    return repository_root() / DEFAULT_SCHEMA_RELATIVE_PATH


def default_fixture_catalog_path() -> Path:
    return repository_root() / DEFAULT_FIXTURE_CATALOG_RELATIVE_PATH


def default_live_catalog_path() -> Path:
    return repository_root() / DEFAULT_LIVE_CATALOG_RELATIVE_PATH


def default_compliance_receipt_path() -> Path:
    return repository_root() / DEFAULT_COMPLIANCE_RECEIPT_RELATIVE_PATH


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogSchemaError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise CatalogSchemaError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise CatalogSchemaError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogSchemaError(f"{name} must be a boolean")
    return value


def _require_sha256(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=64).lower()
    if not _SHA256_RE.fullmatch(text):
        raise CatalogSchemaError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _require_http_url(value: Any, name: str) -> str:
    from urllib.parse import urlparse

    text = _require_non_empty_str(value, name, maximum=2048)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CatalogSchemaError(f"{name} must be an absolute http(s) URL")
    return text


def parse_utc_timestamp(value: Any, *, name: str = "timestamp") -> datetime:
    """Parse a strict ``...Z`` UTC timestamp into an aware datetime."""

    text = _require_non_empty_str(value, name, maximum=40)
    if not _UTC_TIMESTAMP_RE.fullmatch(text):
        raise CatalogSchemaError(
            f"{name} must be an RFC3339 UTC timestamp ending in Z, got {value!r}"
        )
    # fromisoformat accepts "+00:00" but not trailing Z before 3.11-compat path.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CatalogSchemaError(f"{name} is not a valid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise CatalogSchemaError(f"{name} must be timezone-aware UTC")
    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise CatalogSchemaError("timestamp must be timezone-aware UTC")
    utc = value.astimezone(timezone.utc)
    # Normalize fractional seconds out for stable fixtures unless present.
    if utc.microsecond:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_verifier_now() -> datetime:
    """Return the fixed fixture verifier clock (non-authorizing)."""

    return parse_utc_timestamp(FIXTURE_VERIFIER_CLOCK_UTC, name="fixture_verifier_clock")


def normalize_spdx(value: Any, *, name: str = "license_spdx") -> str:
    """Normalize and shape-check an SPDX or LicenseRef identifier.

    LCR-077 accepts a closed allow-list of common SPDX short forms plus
    ``LicenseRef-*`` custom identifiers. LCR-082 will rebind this to a
    vendored canonical registry with digests.
    """

    text = _require_non_empty_str(value, name, maximum=160)
    # Reject generic card-only labels that are not SPDX identifiers.
    lowered = text.lower().replace(" ", "-")
    card_only_labels = {
        "other",
        "unknown",
        "license",
        "proprietary",
        "all-rights-reserved",
        "all_rights_reserved",
        "unlicense",
        "custom",
        "see-license",
        "see_license",
        "none",
    }
    if lowered in card_only_labels:
        raise CardOnlyEvidenceError(
            f"{name}={text!r} is a dataset-card style label and does not prove "
            "redistribution admissibility; record an SPDX id or LicenseRef-*"
        )
    if not _SPDX_ID_RE.fullmatch(text):
        raise CatalogSchemaError(
            f"{name}={text!r} is not an accepted SPDX short-form identifier or LicenseRef-*"
        )
    return text


def is_licenseref(spdx_id: str) -> bool:
    return spdx_id.startswith("LicenseRef-")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TermsEvidence:
    """Observed terms-of-use evidence for one source."""

    terms_url: str
    observed_at: str
    digest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "terms_url": self.terms_url,
            "observed_at": self.observed_at,
            "digest_sha256": self.digest_sha256,
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "terms") -> "TermsEvidence":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        observed_at = _require_non_empty_str(
            value.get("observed_at"), f"{context}.observed_at", maximum=40
        )
        parse_utc_timestamp(observed_at, name=f"{context}.observed_at")
        return cls(
            terms_url=_require_http_url(value.get("terms_url"), f"{context}.terms_url"),
            observed_at=observed_at,
            digest_sha256=_require_sha256(
                value.get("digest_sha256"), f"{context}.digest_sha256"
            ),
        )


@dataclass(frozen=True)
class RobotsEvidence:
    """Observed robots / access evidence for one source."""

    robots_url: str
    observed_at: str
    digest_sha256: str
    access_disposition: RobotsAccessDisposition
    conditions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "robots_url": self.robots_url,
            "observed_at": self.observed_at,
            "digest_sha256": self.digest_sha256,
            "access_disposition": self.access_disposition.value,
        }
        if self.conditions:
            payload["conditions"] = list(self.conditions)
        return payload

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "robots") -> "RobotsEvidence":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        observed_at = _require_non_empty_str(
            value.get("observed_at"), f"{context}.observed_at", maximum=40
        )
        parse_utc_timestamp(observed_at, name=f"{context}.observed_at")
        raw_conditions = value.get("conditions") or []
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise CatalogSchemaError(f"{context}.conditions must be a list of strings")
        conditions = tuple(
            _require_non_empty_str(item, f"{context}.conditions", maximum=512)
            for item in raw_conditions
        )
        return cls(
            robots_url=_require_http_url(value.get("robots_url"), f"{context}.robots_url"),
            observed_at=observed_at,
            digest_sha256=_require_sha256(
                value.get("digest_sha256"), f"{context}.digest_sha256"
            ),
            access_disposition=RobotsAccessDisposition.coerce(
                value.get("access_disposition")
            ),
            conditions=conditions,
        )


@dataclass(frozen=True)
class Permissions:
    """Explicit operation permissions required for transformed immutable release."""

    redistribution: bool
    derivatives: bool
    archive: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "redistribution": self.redistribution,
            "derivatives": self.derivatives,
            "archive": self.archive,
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "permissions") -> "Permissions":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        return cls(
            redistribution=_require_bool(
                value.get("redistribution"), f"{context}.redistribution"
            ),
            derivatives=_require_bool(value.get("derivatives"), f"{context}.derivatives"),
            archive=_require_bool(value.get("archive"), f"{context}.archive"),
        )

    def all_required_granted(self) -> bool:
        return bool(self.redistribution and self.derivatives and self.archive)


@dataclass(frozen=True)
class LicenseRefDefinition:
    """Definition binding for a custom LicenseRef identifier."""

    definition_url: str
    text_digest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition_url": self.definition_url,
            "text_digest_sha256": self.text_digest_sha256,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "license_ref"
    ) -> "LicenseRefDefinition":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        return cls(
            definition_url=_require_http_url(
                value.get("definition_url"), f"{context}.definition_url"
            ),
            text_digest_sha256=_require_sha256(
                value.get("text_digest_sha256"), f"{context}.text_digest_sha256"
            ),
        )


@dataclass(frozen=True)
class SourceRightsRecord:
    """One source + content-scope rights record."""

    record_id: str
    source_id: str
    corpus_family: CorpusFamily
    dataset_repo_id: str
    content_scope: ContentScope
    rights_disposition: RightsDisposition
    license_spdx: str
    legal_basis: LegalBasis
    terms: TermsEvidence
    robots: RobotsEvidence
    permissions: Permissions
    attribution_notice: str
    review_status: ReviewStatus
    reviewed_at: str
    sealed_at: str
    source_url: str
    jurisdiction_or_authority: str
    notes: str = ""
    license_ref: Optional[LicenseRefDefinition] = None
    dataset_card_label: Optional[str] = None
    conditions: tuple[str, ...] = ()
    # Explicit marker: card label alone is never sufficient.
    card_label_is_not_authority: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "corpus_family": self.corpus_family.value,
            "dataset_repo_id": self.dataset_repo_id,
            "content_scope": self.content_scope.value,
            "rights_disposition": self.rights_disposition.value,
            "license_spdx": self.license_spdx,
            "legal_basis": self.legal_basis.value,
            "terms": self.terms.to_dict(),
            "robots": self.robots.to_dict(),
            "permissions": self.permissions.to_dict(),
            "attribution_notice": self.attribution_notice,
            "review_status": self.review_status.value,
            "reviewed_at": self.reviewed_at,
            "sealed_at": self.sealed_at,
            "source_url": self.source_url,
            "jurisdiction_or_authority": self.jurisdiction_or_authority,
            "card_label_is_not_authority": self.card_label_is_not_authority,
        }
        if self.notes:
            payload["notes"] = self.notes
        if self.license_ref is not None:
            payload["license_ref"] = self.license_ref.to_dict()
        if self.dataset_card_label is not None:
            payload["dataset_card_label"] = self.dataset_card_label
        if self.conditions:
            payload["conditions"] = list(self.conditions)
        return payload

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "record"
    ) -> "SourceRightsRecord":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")

        record_id = _require_non_empty_str(
            value.get("record_id"), f"{context}.record_id", maximum=128
        )
        if not _SCOPE_ID_RE.fullmatch(record_id):
            raise CatalogSchemaError(f"{context}.record_id has invalid shape: {record_id!r}")

        source_id = _require_non_empty_str(
            value.get("source_id"), f"{context}.source_id", maximum=128
        )
        if not _SOURCE_ID_RE.fullmatch(source_id):
            raise CatalogSchemaError(f"{context}.source_id has invalid shape: {source_id!r}")

        corpus = CorpusFamily.coerce(value.get("corpus_family"))
        dataset_repo_id = _require_non_empty_str(
            value.get("dataset_repo_id", corpus.dataset_repo_id),
            f"{context}.dataset_repo_id",
            maximum=128,
        )
        if dataset_repo_id not in TARGET_DATASET_REPO_IDS:
            raise CatalogSchemaError(
                f"{context}.dataset_repo_id={dataset_repo_id!r} is not a target corpus"
            )
        if dataset_repo_id != corpus.dataset_repo_id:
            raise CatalogSchemaError(
                f"{context}.dataset_repo_id {dataset_repo_id!r} does not match "
                f"corpus_family={corpus.value} (expected {corpus.dataset_repo_id!r})"
            )

        content_scope = ContentScope.coerce(value.get("content_scope"))
        rights_disposition = RightsDisposition.coerce(value.get("rights_disposition"))
        license_spdx = normalize_spdx(value.get("license_spdx"), name=f"{context}.license_spdx")
        legal_basis = LegalBasis.coerce(value.get("legal_basis"))

        terms_raw = value.get("terms")
        if not isinstance(terms_raw, Mapping):
            raise CatalogSchemaError(f"{context}.terms must be a mapping")
        terms = TermsEvidence.from_mapping(terms_raw, context=f"{context}.terms")

        robots_raw = value.get("robots")
        if not isinstance(robots_raw, Mapping):
            raise CatalogSchemaError(f"{context}.robots must be a mapping")
        robots = RobotsEvidence.from_mapping(robots_raw, context=f"{context}.robots")

        permissions_raw = value.get("permissions")
        if not isinstance(permissions_raw, Mapping):
            raise CatalogSchemaError(f"{context}.permissions must be a mapping")
        permissions = Permissions.from_mapping(
            permissions_raw, context=f"{context}.permissions"
        )

        attribution = _require_non_empty_str(
            value.get("attribution_notice"),
            f"{context}.attribution_notice",
            maximum=4096,
        )
        review_status = ReviewStatus.coerce(value.get("review_status"))
        reviewed_at = _require_non_empty_str(
            value.get("reviewed_at"), f"{context}.reviewed_at", maximum=40
        )
        parse_utc_timestamp(reviewed_at, name=f"{context}.reviewed_at")
        sealed_at = _require_non_empty_str(
            value.get("sealed_at"), f"{context}.sealed_at", maximum=40
        )
        parse_utc_timestamp(sealed_at, name=f"{context}.sealed_at")
        source_url = _require_http_url(value.get("source_url"), f"{context}.source_url")
        jurisdiction = _require_non_empty_str(
            value.get("jurisdiction_or_authority"),
            f"{context}.jurisdiction_or_authority",
            maximum=128,
        )
        notes = str(value.get("notes") or "").strip()

        license_ref: Optional[LicenseRefDefinition] = None
        license_ref_raw = value.get("license_ref")
        if is_licenseref(license_spdx):
            if not isinstance(license_ref_raw, Mapping):
                raise CatalogSchemaError(
                    f"{context}.license_ref is required for LicenseRef identifiers"
                )
            license_ref = LicenseRefDefinition.from_mapping(
                license_ref_raw, context=f"{context}.license_ref"
            )
        elif license_ref_raw is not None:
            if not isinstance(license_ref_raw, Mapping):
                raise CatalogSchemaError(f"{context}.license_ref must be a mapping when present")
            license_ref = LicenseRefDefinition.from_mapping(
                license_ref_raw, context=f"{context}.license_ref"
            )

        dataset_card_label = value.get("dataset_card_label")
        if dataset_card_label is not None:
            dataset_card_label = _require_non_empty_str(
                dataset_card_label, f"{context}.dataset_card_label", maximum=128
            )

        raw_conditions = value.get("conditions") or []
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise CatalogSchemaError(f"{context}.conditions must be a list of strings")
        conditions = tuple(
            _require_non_empty_str(item, f"{context}.conditions", maximum=512)
            for item in raw_conditions
        )

        card_label_is_not_authority = value.get("card_label_is_not_authority", True)
        if not isinstance(card_label_is_not_authority, bool):
            raise CatalogSchemaError(
                f"{context}.card_label_is_not_authority must be a boolean"
            )
        if card_label_is_not_authority is not True:
            raise CatalogSchemaError(
                f"{context}.card_label_is_not_authority must be true; "
                "dataset-card labels never authorize redistribution"
            )

        return cls(
            record_id=record_id,
            source_id=source_id,
            corpus_family=corpus,
            dataset_repo_id=dataset_repo_id,
            content_scope=content_scope,
            rights_disposition=rights_disposition,
            license_spdx=license_spdx,
            legal_basis=legal_basis,
            terms=terms,
            robots=robots,
            permissions=permissions,
            attribution_notice=attribution,
            review_status=review_status,
            reviewed_at=reviewed_at,
            sealed_at=sealed_at,
            source_url=source_url,
            jurisdiction_or_authority=jurisdiction,
            notes=notes,
            license_ref=license_ref,
            dataset_card_label=dataset_card_label,
            conditions=conditions,
            card_label_is_not_authority=card_label_is_not_authority,
        )


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of evaluating one source/content-scope rights record."""

    admitted: bool
    record_id: str
    source_id: str
    content_scope: str
    rights_disposition: str
    reason_codes: tuple[str, ...]
    message: str
    authorizing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "record_id": self.record_id,
            "source_id": self.source_id,
            "content_scope": self.content_scope,
            "rights_disposition": self.rights_disposition,
            "reason_codes": list(self.reason_codes),
            "message": self.message,
            "authorizing": self.authorizing,
        }


@dataclass(frozen=True)
class SourceRightsCatalog:
    """Sealed catalog of per-source / per-content-scope rights records."""

    schema_version: str
    task_id: str
    goal_id: str
    evidence_mode: EvidenceMode
    producer: str
    sealed_at: str
    records: tuple[SourceRightsRecord, ...]
    description: str = ""
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    policy_schema_version: str = SCHEMA_VERSION
    authorizing_for_publication: bool = False
    target_dataset_repo_ids: tuple[str, ...] = (
        STATE_DATASET_REPO_ID,
        FEDERAL_DATASET_REPO_ID,
    )
    raw_payload: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def record_ids(self) -> tuple[str, ...]:
        return tuple(record.record_id for record in self.records)

    def get(self, record_id: str) -> SourceRightsRecord:
        for record in self.records:
            if record.record_id == record_id:
                return record
        raise CatalogSchemaError(f"unknown record_id: {record_id!r}")

    def records_for_source(self, source_id: str) -> tuple[SourceRightsRecord, ...]:
        return tuple(r for r in self.records if r.source_id == source_id)

    def records_for_corpus(self, corpus: CorpusFamily | str) -> tuple[SourceRightsRecord, ...]:
        family = CorpusFamily.coerce(corpus)
        return tuple(r for r in self.records if r.corpus_family is family)

    def catalog_digest_sha256(self) -> str:
        """Content digest of the catalog payload excluding volatile raw_payload."""

        if self.raw_payload:
            # Prefer digest of the on-disk payload without any injected fields.
            payload = dict(self.raw_payload)
            payload.pop("catalog_digest_sha256", None)
            return sha256_json(payload)
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "evidence_mode": self.evidence_mode.value,
            "producer": self.producer,
            "sealed_at": self.sealed_at,
            "policy_schema_version": self.policy_schema_version,
            "authorizing_for_publication": self.authorizing_for_publication,
            "target_dataset_repo_ids": list(self.target_dataset_repo_ids),
            "description": self.description,
            "currentness_disclaimer": self.currentness_disclaimer,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "catalog"
    ) -> "SourceRightsCatalog":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")

        schema_version = _require_non_empty_str(
            value.get("schema_version"), f"{context}.schema_version", maximum=128
        )
        if schema_version != CATALOG_SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"{context}.schema_version must be {CATALOG_SCHEMA_VERSION!r}, "
                f"got {schema_version!r}"
            )
        task_id = _require_non_empty_str(value.get("task_id"), f"{context}.task_id", maximum=32)
        if task_id != TASK_ID:
            raise CatalogSchemaError(
                f"{context}.task_id must be {TASK_ID!r}, got {task_id!r}"
            )
        goal_id = _require_non_empty_str(value.get("goal_id"), f"{context}.goal_id", maximum=32)
        if goal_id != GOAL_ID:
            raise CatalogSchemaError(
                f"{context}.goal_id must be {GOAL_ID!r}, got {goal_id!r}"
            )
        evidence_mode = EvidenceMode.coerce(value.get("evidence_mode"))
        producer = _require_non_empty_str(
            value.get("producer"), f"{context}.producer", maximum=256
        )
        sealed_at = _require_non_empty_str(
            value.get("sealed_at"), f"{context}.sealed_at", maximum=40
        )
        parse_utc_timestamp(sealed_at, name=f"{context}.sealed_at")

        policy_schema_version = _require_non_empty_str(
            value.get("policy_schema_version", SCHEMA_VERSION),
            f"{context}.policy_schema_version",
            maximum=128,
        )
        if policy_schema_version != SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"{context}.policy_schema_version must be {SCHEMA_VERSION!r}, "
                f"got {policy_schema_version!r}"
            )

        authorizing = value.get("authorizing_for_publication", False)
        if not isinstance(authorizing, bool):
            raise CatalogSchemaError(
                f"{context}.authorizing_for_publication must be a boolean"
            )
        # Fixture catalogs are never authorizing; live catalogs may only claim
        # authorization after LCR-078 seals live evidence (still checked here).
        if evidence_mode is EvidenceMode.FIXTURE and authorizing:
            raise CatalogSchemaError(
                f"{context}: fixture evidence_mode cannot set "
                "authorizing_for_publication=true"
            )

        targets_raw = value.get("target_dataset_repo_ids") or list(TARGET_DATASET_REPO_IDS)
        if not isinstance(targets_raw, Sequence) or isinstance(targets_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.target_dataset_repo_ids must be a list")
        targets = tuple(
            _require_non_empty_str(item, f"{context}.target_dataset_repo_ids", maximum=128)
            for item in targets_raw
        )
        if frozenset(targets) != TARGET_DATASET_REPO_IDS:
            raise CatalogSchemaError(
                f"{context}.target_dataset_repo_ids must equal the sealed two-corpus set"
            )

        records_raw = value.get("records")
        if not isinstance(records_raw, Sequence) or isinstance(records_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.records must be a list")
        if not records_raw:
            raise CatalogSchemaError(f"{context}.records must be non-empty")

        records = tuple(
            SourceRightsRecord.from_mapping(item, context=f"{context}.records[{idx}]")
            for idx, item in enumerate(records_raw)
        )
        ids = [record.record_id for record in records]
        if len(ids) != len(set(ids)):
            raise CatalogSchemaError(f"{context}.records record_id values must be unique")

        # Require that fixtures (and live catalogs) distinguish government text
        # from presentation/annotation/editorial/database scopes by including
        # at least one of each major class when in fixture mode.
        scopes_present = {record.content_scope for record in records}
        if evidence_mode is EvidenceMode.FIXTURE:
            required_scopes = {
                ContentScope.STATUTORY_TEXT,
                ContentScope.FEDERAL_GOVERNMENT_TEXT,
                ContentScope.SITE_PRESENTATION,
                ContentScope.ANNOTATIONS,
                ContentScope.EDITORIAL_ENHANCEMENTS,
                ContentScope.DATABASE_CONTENT,
            }
            missing_scopes = sorted(s.value for s in (required_scopes - scopes_present))
            if missing_scopes:
                raise CatalogSchemaError(
                    f"{context}: fixture catalog must distinguish all content scopes; "
                    f"missing={missing_scopes!r}"
                )

        description = str(value.get("description") or "").strip()
        disclaimer = str(value.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER).strip()

        return cls(
            schema_version=schema_version,
            task_id=task_id,
            goal_id=goal_id,
            evidence_mode=evidence_mode,
            producer=producer,
            sealed_at=sealed_at,
            records=records,
            description=description,
            currentness_disclaimer=disclaimer,
            policy_schema_version=policy_schema_version,
            authorizing_for_publication=authorizing,
            target_dataset_repo_ids=targets,
            raw_payload=MappingProxyType(dict(value)),
        )


# ---------------------------------------------------------------------------
# Evaluator (deny-on-unknown)
# ---------------------------------------------------------------------------


def _deny(
    record: SourceRightsRecord,
    *,
    reason_codes: Sequence[str],
    message: str,
    authorizing: bool = False,
) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=False,
        record_id=record.record_id,
        source_id=record.source_id,
        content_scope=record.content_scope.value,
        rights_disposition=record.rights_disposition.value,
        reason_codes=tuple(reason_codes),
        message=message,
        authorizing=authorizing,
    )


def _admit(
    record: SourceRightsRecord,
    *,
    authorizing: bool,
    reason_codes: Sequence[str] = ("admitted",),
    message: str = "scope admitted under source-rights policy",
) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=True,
        record_id=record.record_id,
        source_id=record.source_id,
        content_scope=record.content_scope.value,
        rights_disposition=record.rights_disposition.value,
        reason_codes=tuple(reason_codes),
        message=message,
        authorizing=authorizing,
    )


def evaluate_scope_rights(
    record: SourceRightsRecord | JsonMapping,
    *,
    expected_content_scope: ContentScope | str | None = None,
    expected_source_id: str | None = None,
    expected_corpus: CorpusFamily | str | None = None,
    expected_dataset_repo_id: str | None = None,
    now: datetime | None = None,
    max_evidence_age: timedelta = DEFAULT_MAX_EVIDENCE_AGE,
    max_future_skew: timedelta = DEFAULT_MAX_FUTURE_SKEW,
    authorizing_mode: bool = False,
) -> AdmissionDecision:
    """Evaluate one source/content-scope rights record under deny-on-unknown rules.

    Parameters
    ----------
    record:
        A :class:`SourceRightsRecord` or raw mapping.
    expected_content_scope:
        When provided, the record's content scope must match exactly.
    expected_source_id / expected_corpus / expected_dataset_repo_id:
        Optional identity bindings; mismatch fails closed.
    now:
        Trusted verifier clock. Defaults to the fixed fixture clock when
        ``authorizing_mode`` is false; authorizing/live callers must supply
        an explicit clock.
    authorizing_mode:
        When true, admission is publication-authorizing only if all gates pass
        *and* the caller supplied an explicit trusted clock. Fixture success
        always sets ``authorizing=False`` on the decision.
    """

    if isinstance(record, Mapping):
        parsed = SourceRightsRecord.from_mapping(record)
    elif isinstance(record, SourceRightsRecord):
        parsed = record
    else:
        raise CatalogSchemaError("record must be a SourceRightsRecord or mapping")

    if authorizing_mode and now is None:
        return _deny(
            parsed,
            reason_codes=("missing_trusted_clock",),
            message=(
                "authorizing evaluation requires an explicit trusted verifier clock; "
                "catalog timestamps are not authority"
            ),
        )

    verifier_now = now if now is not None else fixture_verifier_now()
    if verifier_now.tzinfo is None:
        raise CatalogSchemaError("verifier now must be timezone-aware UTC")
    verifier_now = verifier_now.astimezone(timezone.utc)

    # --- Identity bindings -------------------------------------------------
    if expected_source_id is not None and parsed.source_id != expected_source_id:
        return _deny(
            parsed,
            reason_codes=("source_id_mismatch",),
            message=(
                f"source_id {parsed.source_id!r} does not match expected "
                f"{expected_source_id!r}"
            ),
        )
    if expected_corpus is not None:
        family = CorpusFamily.coerce(expected_corpus)
        if parsed.corpus_family is not family:
            return _deny(
                parsed,
                reason_codes=("corpus_mismatch",),
                message=(
                    f"corpus_family {parsed.corpus_family.value!r} does not match "
                    f"expected {family.value!r}"
                ),
            )
    if expected_dataset_repo_id is not None:
        if parsed.dataset_repo_id != expected_dataset_repo_id:
            return _deny(
                parsed,
                reason_codes=("dataset_repo_mismatch",),
                message=(
                    f"dataset_repo_id {parsed.dataset_repo_id!r} does not match "
                    f"expected {expected_dataset_repo_id!r}"
                ),
            )
    if expected_content_scope is not None:
        expected_scope = ContentScope.coerce(expected_content_scope)
        if parsed.content_scope is not expected_scope:
            return _deny(
                parsed,
                reason_codes=("scope_mismatch",),
                message=(
                    f"content_scope {parsed.content_scope.value!r} does not match "
                    f"expected {expected_scope.value!r}"
                ),
            )

    # --- Card-label authority fence ----------------------------------------
    if parsed.card_label_is_not_authority is not True:
        return _deny(
            parsed,
            reason_codes=("card_label_claimed_authority",),
            message="dataset-card labels must never be treated as rights authority",
        )

    # --- Content-scope class gates ----------------------------------------
    if parsed.content_scope in DEFAULT_QUARANTINED_CONTENT_SCOPES:
        return _deny(
            parsed,
            reason_codes=("presentation_or_enhancement_scope", parsed.content_scope.value),
            message=(
                f"content scope {parsed.content_scope.value!r} (site presentation, "
                "annotations, editorial enhancements, or database content) is not "
                "admissible into the default release"
            ),
        )
    if parsed.content_scope not in ADMISSIBLE_CONTENT_SCOPES:
        return _deny(
            parsed,
            reason_codes=("unsupported_content_scope",),
            message=f"content scope {parsed.content_scope.value!r} is unsupported",
        )

    # --- Disposition -------------------------------------------------------
    disposition = parsed.rights_disposition
    if disposition is RightsDisposition.PROHIBITED:
        return _deny(
            parsed,
            reason_codes=("prohibited",),
            message="rights disposition is prohibited",
        )
    if disposition is RightsDisposition.UNKNOWN:
        return _deny(
            parsed,
            reason_codes=("unknown_rights",),
            message="rights disposition is unknown (deny-on-unknown)",
        )
    if disposition is RightsDisposition.UNSUPPORTED:
        return _deny(
            parsed,
            reason_codes=("unsupported_rights",),
            message="rights disposition is unsupported",
        )
    if disposition is RightsDisposition.QUARANTINED:
        return _deny(
            parsed,
            reason_codes=("quarantined",),
            message="rights disposition is quarantined out of the default release",
        )
    if disposition is RightsDisposition.CONDITIONAL:
        # Conditional requires explicit conditions and matching robots conditions.
        if not parsed.conditions:
            return _deny(
                parsed,
                reason_codes=("conditional_without_conditions",),
                message="conditional disposition requires explicit conditions",
            )
        # For LCR-077, conditional is not admitted into the default release.
        # LCR-082 may admit fully modeled conditional evidence.
        return _deny(
            parsed,
            reason_codes=("conditional_not_default_admissible",),
            message=(
                "conditional rights are not admitted into the default release "
                "under LCR-077 (deny-on-unknown for unmodeled conditions)"
            ),
        )
    if disposition is not RightsDisposition.ALLOWED:
        return _deny(
            parsed,
            reason_codes=("non_allowed_disposition",),
            message=f"rights disposition {disposition.value!r} is not allowed",
        )

    # --- Legal basis -------------------------------------------------------
    if not parsed.legal_basis.supports_default_admission:
        return _deny(
            parsed,
            reason_codes=("legal_basis_inadmissible", parsed.legal_basis.value),
            message=(
                f"legal basis {parsed.legal_basis.value!r} does not support "
                "default-release admission"
            ),
        )

    # --- LicenseRef binding ------------------------------------------------
    if is_licenseref(parsed.license_spdx):
        if parsed.license_ref is None:
            return _deny(
                parsed,
                reason_codes=("licenseref_undefined",),
                message="LicenseRef identifiers require definition_url and text digest",
            )

    # --- Permissions -------------------------------------------------------
    if not parsed.permissions.all_required_granted():
        missing = []
        if not parsed.permissions.redistribution:
            missing.append("redistribution")
        if not parsed.permissions.derivatives:
            missing.append("derivatives")
        if not parsed.permissions.archive:
            missing.append("archive")
        return _deny(
            parsed,
            reason_codes=("permissions_incomplete", *missing),
            message=(
                "transformed immutable release requires redistribution, derivatives, "
                f"and archive permissions; missing={missing!r}"
            ),
        )

    # --- Robots / access ---------------------------------------------------
    robots = parsed.robots.access_disposition
    if robots is RobotsAccessDisposition.DENIED:
        return _deny(
            parsed,
            reason_codes=("robots_denied",),
            message="robots/access disposition is denied",
        )
    if robots is RobotsAccessDisposition.UNKNOWN:
        return _deny(
            parsed,
            reason_codes=("robots_unknown",),
            message="robots/access disposition is unknown (deny-on-unknown)",
        )
    if robots is RobotsAccessDisposition.UNAVAILABLE:
        return _deny(
            parsed,
            reason_codes=("robots_unavailable",),
            message="robots/access disposition is unavailable",
        )
    if robots is RobotsAccessDisposition.CONDITIONAL:
        if not parsed.robots.conditions:
            return _deny(
                parsed,
                reason_codes=("robots_conditional_unmodeled",),
                message="conditional robots access requires modeled conditions",
            )
        # LCR-077: conditional robots do not admit into default release.
        return _deny(
            parsed,
            reason_codes=("robots_conditional_not_default_admissible",),
            message="conditional robots access is not default-release admissible under LCR-077",
        )
    if robots is not RobotsAccessDisposition.ALLOWED:
        return _deny(
            parsed,
            reason_codes=("robots_not_allowed",),
            message=f"robots/access disposition {robots.value!r} is not allowed",
        )

    # --- Review ------------------------------------------------------------
    if parsed.review_status is ReviewStatus.UNREVIEWED:
        return _deny(
            parsed,
            reason_codes=("unreviewed",),
            message="rights record is unreviewed",
        )
    if parsed.review_status is ReviewStatus.REJECTED:
        return _deny(
            parsed,
            reason_codes=("review_rejected",),
            message="rights review was rejected",
        )
    if parsed.review_status is ReviewStatus.EXPIRED:
        return _deny(
            parsed,
            reason_codes=("review_expired",),
            message="rights review has expired",
        )
    if parsed.review_status is not ReviewStatus.REVIEWED:
        return _deny(
            parsed,
            reason_codes=("review_status_invalid",),
            message=f"review status {parsed.review_status.value!r} is not admitted",
        )

    # --- Temporal freshness / order ----------------------------------------
    terms_at = parse_utc_timestamp(parsed.terms.observed_at, name="terms.observed_at")
    robots_at = parse_utc_timestamp(parsed.robots.observed_at, name="robots.observed_at")
    reviewed_at = parse_utc_timestamp(parsed.reviewed_at, name="reviewed_at")
    sealed_at = parse_utc_timestamp(parsed.sealed_at, name="sealed_at")

    # Evidence must not be after review, seal, or verifier now (within skew).
    latest_allowed = verifier_now + max_future_skew
    for label, ts in (
        ("terms.observed_at", terms_at),
        ("robots.observed_at", robots_at),
        ("reviewed_at", reviewed_at),
        ("sealed_at", sealed_at),
    ):
        if ts > latest_allowed:
            return _deny(
                parsed,
                reason_codes=("future_timestamp", label),
                message=f"{label} is after trusted verifier time (future/self-selected seal)",
            )

    if terms_at > reviewed_at:
        return _deny(
            parsed,
            reason_codes=("terms_after_review",),
            message="terms.observed_at must be at or before reviewed_at",
        )
    if robots_at > reviewed_at:
        return _deny(
            parsed,
            reason_codes=("robots_after_review",),
            message="robots.observed_at must be at or before reviewed_at",
        )
    if reviewed_at > sealed_at:
        return _deny(
            parsed,
            reason_codes=("review_after_seal",),
            message="reviewed_at must be at or before sealed_at",
        )
    if sealed_at > latest_allowed:
        return _deny(
            parsed,
            reason_codes=("seal_after_verifier",),
            message="sealed_at is after trusted verifier time",
        )

    oldest_allowed = verifier_now - max_evidence_age
    for label, ts in (
        ("terms.observed_at", terms_at),
        ("robots.observed_at", robots_at),
        ("reviewed_at", reviewed_at),
    ):
        if ts < oldest_allowed:
            return _deny(
                parsed,
                reason_codes=("stale_evidence", label),
                message=f"{label} is older than max evidence age ({max_evidence_age!s})",
            )

    # --- Attribution -------------------------------------------------------
    if not parsed.attribution_notice.strip():
        return _deny(
            parsed,
            reason_codes=("missing_attribution",),
            message="attribution_notice is required",
        )

    authorizing = bool(authorizing_mode and now is not None)
    return _admit(
        parsed,
        authorizing=authorizing,
        reason_codes=("admitted", "evidence_current", "scope_government_or_statutory"),
        message=(
            "scope admitted: government/statutory text with current allowed "
            "evidence, SPDX/LicenseRef identity, and required permissions"
        ),
    )


def require_scope_rights(
    record: SourceRightsRecord | JsonMapping,
    **kwargs: Any,
) -> AdmissionDecision:
    """Evaluate and raise :class:`RightsAdmissionError` when not admitted."""

    decision = evaluate_scope_rights(record, **kwargs)
    if not decision.admitted:
        code = decision.reason_codes[0] if decision.reason_codes else "denied"
        if code == "scope_mismatch":
            raise ScopeMismatchError(decision.message)
        if code in {"prohibited", "presentation_or_enhancement_scope"}:
            raise ProhibitedScopeError(decision.message)
        if code in {"unknown_rights", "unsupported_rights", "unsupported_content_scope"}:
            raise UnknownRightsError(decision.message)
        if code == "stale_evidence" or code.startswith("stale"):
            raise StaleEvidenceError(decision.message)
        if code in {"card_label_claimed_authority"}:
            raise CardOnlyEvidenceError(decision.message)
        raise RightsAdmissionError(
            f"rights admission denied ({','.join(decision.reason_codes)}): {decision.message}"
        )
    return decision


def admitted_records(
    catalog: SourceRightsCatalog | Iterable[SourceRightsRecord | JsonMapping],
    *,
    now: datetime | None = None,
    authorizing_mode: bool = False,
    **kwargs: Any,
) -> tuple[SourceRightsRecord, ...]:
    """Return only evaluator-admitted records (convenience API parity).

    Every path, including this convenience selector, calls
    :func:`evaluate_scope_rights` with the same trusted clock. No weaker
    filter is exposed.
    """

    if isinstance(catalog, SourceRightsCatalog):
        records: Iterable[SourceRightsRecord] = catalog.records
    else:
        records = catalog  # type: ignore[assignment]

    admitted: list[SourceRightsRecord] = []
    for item in records:
        if isinstance(item, SourceRightsRecord):
            record = item
        else:
            record = SourceRightsRecord.from_mapping(item)
        decision = evaluate_scope_rights(
            record,
            now=now,
            authorizing_mode=authorizing_mode,
            **kwargs,
        )
        if decision.admitted:
            admitted.append(record)
    return tuple(admitted)


def evaluate_catalog(
    catalog: SourceRightsCatalog,
    *,
    now: datetime | None = None,
    authorizing_mode: bool = False,
) -> dict[str, Any]:
    """Evaluate every record and return a structured compliance projection."""

    decisions = [
        evaluate_scope_rights(
            record,
            now=now,
            authorizing_mode=authorizing_mode,
        )
        for record in catalog.records
    ]
    admitted = [d for d in decisions if d.admitted]
    denied = [d for d in decisions if not d.admitted]

    # Group denial reasons for audit visibility.
    denial_counts: dict[str, int] = {}
    for decision in denied:
        key = decision.reason_codes[0] if decision.reason_codes else "denied"
        denial_counts[key] = denial_counts.get(key, 0) + 1

    scopes_admitted = sorted({d.content_scope for d in admitted})
    scopes_denied = sorted({d.content_scope for d in denied})

    authorizing = bool(
        authorizing_mode
        and catalog.evidence_mode is EvidenceMode.LIVE
        and catalog.authorizing_for_publication
        and now is not None
        and all(d.admitted and d.authorizing for d in admitted)
        and bool(admitted)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_schema_version": catalog.schema_version,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "evidence_mode": catalog.evidence_mode.value,
        "authorizing_for_publication": authorizing,
        "fixture_only_non_authorizing": catalog.evidence_mode is EvidenceMode.FIXTURE,
        "catalog_digest_sha256": catalog.catalog_digest_sha256(),
        "record_count": len(catalog.records),
        "admitted_count": len(admitted),
        "denied_count": len(denied),
        "admitted_record_ids": [d.record_id for d in admitted],
        "denied_record_ids": [d.record_id for d in denied],
        "admitted_content_scopes": scopes_admitted,
        "denied_content_scopes": scopes_denied,
        "denial_reason_counts": denial_counts,
        "decisions": [d.to_dict() for d in decisions],
        "target_dataset_repo_ids": list(catalog.target_dataset_repo_ids),
        "currentness_disclaimer": catalog.currentness_disclaimer,
    }


def assert_catalog_distinguishes_scopes(catalog: SourceRightsCatalog) -> None:
    """Fail closed when government text is not separated from enhancements."""

    scopes = {record.content_scope for record in catalog.records}
    required = {
        ContentScope.STATUTORY_TEXT,
        ContentScope.FEDERAL_GOVERNMENT_TEXT,
        ContentScope.SITE_PRESENTATION,
        ContentScope.ANNOTATIONS,
        ContentScope.EDITORIAL_ENHANCEMENTS,
        ContentScope.DATABASE_CONTENT,
    }
    missing = sorted(s.value for s in (required - scopes))
    if missing:
        raise CatalogSchemaError(
            f"catalog must distinguish statutory/Federal text from presentation/"
            f"annotations/editorial/database scopes; missing={missing!r}"
        )


# ---------------------------------------------------------------------------
# Load / validate
# ---------------------------------------------------------------------------


def load_catalog_payload(path: PathLike) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise CatalogSchemaError(f"rights catalog not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogSchemaError(f"rights catalog is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogSchemaError(f"rights catalog root must be an object: {path}")
    return payload


def load_source_rights_catalog(path: PathLike | None = None) -> SourceRightsCatalog:
    """Load and parse a source-rights catalog from disk."""

    catalog_path = Path(path) if path is not None else default_fixture_catalog_path()
    payload = load_catalog_payload(catalog_path)
    return SourceRightsCatalog.from_mapping(payload)


@lru_cache(maxsize=4)
def get_fixture_source_rights_catalog() -> SourceRightsCatalog:
    """Cached fixture catalog loader."""

    return load_source_rights_catalog(default_fixture_catalog_path())


def clear_catalog_cache() -> None:
    get_fixture_source_rights_catalog.cache_clear()


def load_schema_document(path: PathLike | None = None) -> dict[str, Any]:
    schema_path = Path(path) if path is not None else default_schema_path()
    if not schema_path.is_file():
        raise CatalogSchemaError(f"rights catalog schema not found: {schema_path}")
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogSchemaError(f"schema is not valid JSON: {schema_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogSchemaError("schema root must be an object")
    return payload


def validate_catalog_against_schema(
    catalog_payload: JsonMapping,
    schema_payload: JsonMapping | None = None,
) -> list[str]:
    """Validate catalog payload against the JSON schema when jsonschema is available.

    Returns a list of error strings (empty when valid). When the optional
    ``jsonschema`` package is absent, performs structural checks already
    enforced by :class:`SourceRightsCatalog.from_mapping` and returns [].
    """

    # Always parse through the policy dataclass gate (authoritative).
    errors: list[str] = []
    try:
        SourceRightsCatalog.from_mapping(catalog_payload)
    except LegalSourceRightsPolicyError as exc:
        errors.append(str(exc))
        return errors

    schema = schema_payload if schema_payload is not None else None
    if schema is None:
        try:
            schema = load_schema_document()
        except CatalogSchemaError:
            # Schema file may be under construction; dataclass validation is enough.
            return errors

    try:
        import jsonschema  # type: ignore
    except ImportError:
        return errors

    validator_cls = getattr(jsonschema, "Draft202012Validator", None)
    if validator_cls is None:
        validator_cls = getattr(jsonschema, "Draft7Validator", None)
    if validator_cls is None:
        return errors

    try:
        validator = validator_cls(schema)
        for error in sorted(validator.iter_errors(catalog_payload), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in error.absolute_path) or "<root>"
            errors.append(f"{path}: {error.message}")
    except Exception as exc:  # noqa: BLE001 - optional schema path must not mask policy gate
        errors.append(f"jsonschema validation error: {exc}")
    return errors


def build_fixture_compliance_projection(
    catalog: SourceRightsCatalog | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a non-authorizing fixture compliance projection for audits."""

    cat = catalog if catalog is not None else get_fixture_source_rights_catalog()
    if cat.evidence_mode is not EvidenceMode.FIXTURE:
        raise CatalogSchemaError(
            "build_fixture_compliance_projection requires evidence_mode=fixture"
        )
    evaluation = evaluate_catalog(cat, now=now or fixture_verifier_now(), authorizing_mode=False)
    evaluation["mode"] = "fixture_only"
    evaluation["authorizing_for_publication"] = False
    evaluation["fixture_only_non_authorizing"] = True
    evaluation["policy_module"] = PRODUCER
    evaluation["policy_schema_version"] = SCHEMA_VERSION
    evaluation["verified_at"] = format_utc_timestamp(now or fixture_verifier_now())
    return evaluation


def audit_fixture_catalog(
    *,
    catalog_path: PathLike | None = None,
    schema_path: PathLike | None = None,
) -> dict[str, Any]:
    """Load the fixture catalog, validate, evaluate, and return the audit report."""

    path = Path(catalog_path) if catalog_path is not None else default_fixture_catalog_path()
    payload = load_catalog_payload(path)
    schema_errors = validate_catalog_against_schema(
        payload,
        schema_payload=load_schema_document(schema_path) if schema_path else None,
    )
    if schema_errors:
        raise CatalogSchemaError(
            "fixture catalog failed schema/policy validation:\n- "
            + "\n- ".join(schema_errors)
        )
    catalog = SourceRightsCatalog.from_mapping(payload)
    assert_catalog_distinguishes_scopes(catalog)
    report = build_fixture_compliance_projection(catalog)
    report["catalog_path"] = str(path.as_posix())
    report["schema_path"] = str(
        (Path(schema_path) if schema_path else default_schema_path()).as_posix()
    )
    report["status"] = "passed"
    # Fixture audits pass when the catalog is well-formed and the evaluator
    # correctly admits government/statutory scopes while denying the rest.
    if report["admitted_count"] < 1:
        raise RightsAdmissionError(
            "fixture catalog must contain at least one admitted government/statutory scope"
        )
    if report["denied_count"] < 1:
        raise RightsAdmissionError(
            "fixture catalog must contain denied presentation/annotation/editorial/"
            "database or unknown/prohibited scopes"
        )
    admitted_scopes = set(report["admitted_content_scopes"])
    if not admitted_scopes.issubset({s.value for s in ADMISSIBLE_CONTENT_SCOPES}):
        raise RightsAdmissionError(
            f"fixture admitted non-government scopes: {sorted(admitted_scopes)!r}"
        )
    return report


def require_live_source_evidence(
    *,
    catalog_path: PathLike | None = None,
) -> SourceRightsCatalog:
    """Load the live catalog or fail closed when live evidence is required."""

    path = Path(catalog_path) if catalog_path is not None else default_live_catalog_path()
    if not path.is_file():
        raise LiveEvidenceRequiredError(
            f"live source-rights catalog is required but missing: {path}. "
            "Run LCR-078 to seal live evidence; fixture-only success is non-authorizing."
        )
    catalog = load_source_rights_catalog(path)
    if catalog.evidence_mode is not EvidenceMode.LIVE:
        raise LiveEvidenceRequiredError(
            f"catalog at {path} has evidence_mode={catalog.evidence_mode.value!r}; "
            "live evidence is required"
        )
    if not catalog.authorizing_for_publication:
        raise LiveEvidenceRequiredError(
            f"live catalog at {path} is not marked authorizing_for_publication"
        )
    return catalog


__all__ = [
    "ADMISSIBLE_CONTENT_SCOPES",
    "CATALOG_SCHEMA_VERSION",
    "CURRENTNESS_DISCLAIMER",
    "DEFAULT_MAX_EVIDENCE_AGE",
    "DEFAULT_QUARANTINED_CONTENT_SCOPES",
    "FEDERAL_DATASET_REPO_ID",
    "FIXTURE_VERIFIER_CLOCK_UTC",
    "GOAL_ID",
    "PROGRAM_ID",
    "PRODUCER",
    "SCHEMA_VERSION",
    "STATE_DATASET_REPO_ID",
    "TASK_ID",
    "TARGET_DATASET_REPO_IDS",
    "AdmissionDecision",
    "CardOnlyEvidenceError",
    "CatalogSchemaError",
    "ContentScope",
    "CorpusFamily",
    "EvidenceMode",
    "LegalBasis",
    "LegalSourceRightsPolicyError",
    "LicenseRefDefinition",
    "LiveEvidenceRequiredError",
    "Permissions",
    "ProhibitedScopeError",
    "RightsAdmissionError",
    "RightsDisposition",
    "RobotsAccessDisposition",
    "RobotsEvidence",
    "ReviewStatus",
    "ScopeMismatchError",
    "SourceRightsCatalog",
    "SourceRightsRecord",
    "StaleEvidenceError",
    "TermsEvidence",
    "UnknownRightsError",
    "admitted_records",
    "assert_catalog_distinguishes_scopes",
    "audit_fixture_catalog",
    "build_fixture_compliance_projection",
    "canonical_json",
    "clear_catalog_cache",
    "default_compliance_receipt_path",
    "default_fixture_catalog_path",
    "default_live_catalog_path",
    "default_schema_path",
    "evaluate_catalog",
    "evaluate_scope_rights",
    "fixture_verifier_now",
    "format_utc_timestamp",
    "get_fixture_source_rights_catalog",
    "is_licenseref",
    "load_catalog_payload",
    "load_schema_document",
    "load_source_rights_catalog",
    "normalize_spdx",
    "parse_utc_timestamp",
    "repository_root",
    "require_live_source_evidence",
    "require_scope_rights",
    "sha256_file",
    "sha256_json",
    "sha256_text",
    "validate_catalog_against_schema",
]
