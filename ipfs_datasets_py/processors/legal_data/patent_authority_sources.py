"""Patent authority source and receipt registry contracts.

This module owns the reusable source/authority/receipt contract used by
federal authority connectors (CFR, U.S. Code, Federal Register, MPEP, and
related guidance). It deliberately avoids network I/O and USPTO matter types.

Design invariants (PATLAW-011 / source-authority policy):

* Every registered source carries an explicit :class:`AuthorityTier`.
* Edition/version identity must never be the hard-coded token ``"latest"``;
  current endpoints are discovered at runtime and recorded with concrete
  edition, release-point, or revision identifiers.
* Official artifact identity and derived presentation identity are distinct
  fields so eCFR (or similar) presentation cannot impersonate an official
  annual/GovInfo artifact.
* Serialization is deterministic for fixture replay (sorted keys, compact JSON).
* Retry/cache policy is shared configuration only; connectors implement I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional, Sequence


SCHEMA_VERSION = "patent-authority-sources-v1"

# Tokens that must never appear as a concrete edition/version identity.
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_IDENTITY_KEYS = frozenset(
    {
        "edition",
        "version",
        "release_point",
        "revision",
        "source_package",
        "package_id",
        "collection_edition",
    }
)


class PatentAuthoritySourcesError(ValueError):
    """Base error for authority source contract violations."""


class MissingAuthorityTierError(PatentAuthoritySourcesError):
    """Raised when a source is registered without an authority tier."""


class HardCodedLatestEditionError(PatentAuthoritySourcesError):
    """Raised when a source uses a hard-coded ``latest`` edition/version token."""


class AuthoritySourceRegistryError(PatentAuthoritySourcesError):
    """Raised for registry membership and integrity failures."""


class AuthorityTier(str, Enum):
    """Closed authority tiers for patent legal sources.

    Ordered from highest controlling weight to lowest for documentation
    purposes; ranking for temporal resolution lives in the later temporal
    authority graph (PATLAW-016), not in this module.
    """

    OFFICIAL_BASE = "official-base"
    OFFICIAL_CHANGE = "official-change"
    UNOFFICIAL_CURRENT = "unofficial-current"
    GUIDANCE = "guidance"
    CANDIDATE = "candidate"


class VerificationState(str, Enum):
    """Digital/print verification state for a retrieved artifact."""

    VERIFIED = "verified"
    CONFLICT = "conflict"
    INCONCLUSIVE = "inconclusive"
    UNVERIFIED = "unverified"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class IdentityRole(str, Enum):
    """Which identity a connector is recording."""

    OFFICIAL_ARTIFACT = "official_artifact"
    DERIVED_PRESENTATION = "derived_presentation"


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatentAuthoritySourcesError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PatentAuthoritySourcesError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    return _require_non_empty_str(value, name)


def _require_sha256(value: Any, name: str = "artifact_sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PatentAuthoritySourcesError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _is_hard_coded_latest(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and _LATEST_TOKEN_RE.fullmatch(value):
        return True
    return False


def reject_hard_coded_latest(value: Any, *, field_name: str) -> None:
    """Fail closed when *value* is the hard-coded edition token ``latest``."""

    if _is_hard_coded_latest(value):
        raise HardCodedLatestEditionError(
            f"{field_name} must not be the hard-coded token 'latest'; "
            "discover the concrete edition/release at runtime and record it"
        )


def _parse_utc_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PatentAuthoritySourcesError(
                f"{name} must be an ISO-8601 datetime"
            ) from exc
    else:
        raise PatentAuthoritySourcesError(f"{name} must be a datetime or ISO-8601 string")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: datetime) -> str:
    normalized = dt.astimezone(timezone.utc).replace(microsecond=(dt.microsecond // 1000) * 1000)
    # Stable Zulu form for fixtures.
    text = normalized.isoformat().replace("+00:00", "Z")
    return text


def _parse_optional_date(value: Any, *, name: str) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise PatentAuthoritySourcesError(f"{name} must be an ISO date") from exc
    raise PatentAuthoritySourcesError(f"{name} must be a date or ISO date string")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _coerce_authority_tier(value: Any) -> AuthorityTier:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingAuthorityTierError("authority_tier is required")
    if isinstance(value, AuthorityTier):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-")
        for tier in AuthorityTier:
            if tier.value == normalized:
                return tier
        raise MissingAuthorityTierError(
            f"unknown authority_tier {value!r}; expected one of "
            f"{[t.value for t in AuthorityTier]}"
        )
    raise MissingAuthorityTierError("authority_tier is required")


def _coerce_verification_state(value: Any) -> VerificationState:
    if value is None:
        return VerificationState.UNVERIFIED
    if isinstance(value, VerificationState):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        for state in VerificationState:
            if state.value == normalized or state.name.lower() == normalized:
                return state
    raise PatentAuthoritySourcesError(f"unknown verification_state: {value!r}")


def canonical_json_dumps(payload: Mapping[str, Any]) -> str:
    """Return deterministic JSON text for fixtures and content addressing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return UTF-8 bytes of :func:`canonical_json_dumps`."""

    return canonical_json_dumps(payload).encode("utf-8")


@dataclass(frozen=True, slots=True)
class RetryCachePolicy:
    """Shared retry and cache defaults for authority connectors.

    Connectors own transport; this record only freezes policy parameters so
    fixtures and registry entries can pin behavior without inventing rate
    limits.
    """

    max_attempts: int = 5
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 60.0
    jitter_ratio: float = 0.25
    honor_retry_after: bool = True
    circuit_breaker_failures: int = 5
    circuit_breaker_cooldown_seconds: float = 120.0
    cache_ttl_seconds: Optional[float] = None
    enable_conditional_requests: bool = True
    respect_etag: bool = True
    respect_last_modified: bool = True

    def __post_init__(self) -> None:
        if int(self.max_attempts) < 1:
            raise PatentAuthoritySourcesError("max_attempts must be >= 1")
        if float(self.base_backoff_seconds) < 0:
            raise PatentAuthoritySourcesError("base_backoff_seconds must be >= 0")
        if float(self.max_backoff_seconds) < float(self.base_backoff_seconds):
            raise PatentAuthoritySourcesError(
                "max_backoff_seconds must be >= base_backoff_seconds"
            )
        if not (0.0 <= float(self.jitter_ratio) <= 1.0):
            raise PatentAuthoritySourcesError("jitter_ratio must be in [0, 1]")
        if int(self.circuit_breaker_failures) < 1:
            raise PatentAuthoritySourcesError("circuit_breaker_failures must be >= 1")
        if float(self.circuit_breaker_cooldown_seconds) < 0:
            raise PatentAuthoritySourcesError(
                "circuit_breaker_cooldown_seconds must be >= 0"
            )
        if self.cache_ttl_seconds is not None and float(self.cache_ttl_seconds) < 0:
            raise PatentAuthoritySourcesError("cache_ttl_seconds must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_backoff_seconds": float(self.base_backoff_seconds),
            "cache_ttl_seconds": (
                None if self.cache_ttl_seconds is None else float(self.cache_ttl_seconds)
            ),
            "circuit_breaker_cooldown_seconds": float(self.circuit_breaker_cooldown_seconds),
            "circuit_breaker_failures": int(self.circuit_breaker_failures),
            "enable_conditional_requests": bool(self.enable_conditional_requests),
            "honor_retry_after": bool(self.honor_retry_after),
            "jitter_ratio": float(self.jitter_ratio),
            "max_attempts": int(self.max_attempts),
            "max_backoff_seconds": float(self.max_backoff_seconds),
            "respect_etag": bool(self.respect_etag),
            "respect_last_modified": bool(self.respect_last_modified),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "RetryCachePolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise PatentAuthoritySourcesError("retry_cache_policy must be a mapping")
        known = {f.name for f in fields(cls)}
        kwargs = {k: value[k] for k in known if k in value}
        return cls(**kwargs)


DEFAULT_RETRY_CACHE_POLICY = RetryCachePolicy()


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Immutable content identity for one retrieved or derived artifact.

    Required identity fields follow the source-authority policy bundle:
    ``provider``, ``source_id``, ``artifact_sha256``, ``source_url``.
    Retrieval time lives on the :class:`SourceReceipt`, not here.
    """

    provider: str
    source_id: str
    artifact_sha256: str
    source_url: str
    media_type: Optional[str] = None
    byte_size: Optional[int] = None
    upstream_package_id: Optional[str] = None
    role: IdentityRole = IdentityRole.OFFICIAL_ARTIFACT

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _require_non_empty_str(self.provider, "provider"))
        object.__setattr__(self, "source_id", _require_non_empty_str(self.source_id, "source_id"))
        object.__setattr__(
            self, "artifact_sha256", _require_sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        if self.media_type is not None:
            object.__setattr__(
                self, "media_type", _require_non_empty_str(self.media_type, "media_type")
            )
        if self.byte_size is not None:
            if not isinstance(self.byte_size, int) or self.byte_size < 0:
                raise PatentAuthoritySourcesError("byte_size must be a non-negative int")
        if self.upstream_package_id is not None:
            object.__setattr__(
                self,
                "upstream_package_id",
                _require_non_empty_str(self.upstream_package_id, "upstream_package_id"),
            )
            reject_hard_coded_latest(
                self.upstream_package_id, field_name="upstream_package_id"
            )
        if not isinstance(self.role, IdentityRole):
            object.__setattr__(self, "role", IdentityRole(str(self.role)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "provider": self.provider,
            "role": self.role.value,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "upstream_package_id": self.upstream_package_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactIdentity":
        if not isinstance(value, Mapping):
            raise PatentAuthoritySourcesError("artifact identity must be a mapping")
        role_raw = value.get("role", IdentityRole.OFFICIAL_ARTIFACT.value)
        if isinstance(role_raw, IdentityRole):
            role = role_raw
        else:
            role = IdentityRole(str(role_raw))
        return cls(
            provider=value.get("provider"),  # type: ignore[arg-type]
            source_id=value.get("source_id"),  # type: ignore[arg-type]
            artifact_sha256=value.get("artifact_sha256"),  # type: ignore[arg-type]
            source_url=value.get("source_url"),  # type: ignore[arg-type]
            media_type=value.get("media_type"),
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id"),
            role=role,
        )


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """Sanitized retrieval receipt for one authority fetch.

    Captures request envelope (without secrets), endpoint, retrieval UTC,
    response status, upstream identifiers / last-modified, and retry/cache
    metadata. HTTP success alone is not verification.
    """

    endpoint: str
    retrieved_at: datetime
    response_status: int
    sanitized_request: Mapping[str, Any] = field(default_factory=dict)
    upstream_id: Optional[str] = None
    upstream_last_modified: Optional[str] = None
    etag: Optional[str] = None
    retry_count: int = 0
    cache_hit: bool = False
    cache_key: Optional[str] = None
    content_sha256: Optional[str] = None
    media_type: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _require_non_empty_str(self.endpoint, "endpoint"))
        object.__setattr__(
            self, "retrieved_at", _parse_utc_datetime(self.retrieved_at, name="retrieved_at")
        )
        if not isinstance(self.response_status, int):
            raise PatentAuthoritySourcesError("response_status must be an int")
        if self.response_status < 0:
            raise PatentAuthoritySourcesError("response_status must be >= 0")
        if not isinstance(self.sanitized_request, Mapping):
            raise PatentAuthoritySourcesError("sanitized_request must be a mapping")
        # Defensive copy so frozen receipt cannot be mutated via shared dict.
        object.__setattr__(self, "sanitized_request", dict(self.sanitized_request))
        if self.upstream_id is not None:
            object.__setattr__(
                self, "upstream_id", _require_non_empty_str(self.upstream_id, "upstream_id")
            )
        if self.upstream_last_modified is not None:
            object.__setattr__(
                self,
                "upstream_last_modified",
                _require_non_empty_str(self.upstream_last_modified, "upstream_last_modified"),
            )
        if self.etag is not None:
            object.__setattr__(self, "etag", _require_non_empty_str(self.etag, "etag"))
        if not isinstance(self.retry_count, int) or self.retry_count < 0:
            raise PatentAuthoritySourcesError("retry_count must be a non-negative int")
        if self.cache_key is not None:
            object.__setattr__(
                self, "cache_key", _require_non_empty_str(self.cache_key, "cache_key")
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        if self.media_type is not None:
            object.__setattr__(
                self, "media_type", _require_non_empty_str(self.media_type, "media_type")
            )
        if self.error_code is not None:
            object.__setattr__(
                self, "error_code", _require_non_empty_str(self.error_code, "error_code")
            )
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthoritySourcesError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_hit": bool(self.cache_hit),
            "cache_key": self.cache_key,
            "content_sha256": self.content_sha256,
            "endpoint": self.endpoint,
            "error_code": self.error_code,
            "etag": self.etag,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
            "response_status": int(self.response_status),
            "retrieved_at": _format_utc(self.retrieved_at),
            "retry_count": int(self.retry_count),
            "sanitized_request": _deep_sorted_mapping(self.sanitized_request),
            "upstream_id": self.upstream_id,
            "upstream_last_modified": self.upstream_last_modified,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceReceipt":
        if not isinstance(value, Mapping):
            raise PatentAuthoritySourcesError("source receipt must be a mapping")
        return cls(
            endpoint=value["endpoint"],
            retrieved_at=value["retrieved_at"],
            response_status=int(value["response_status"]),
            sanitized_request=value.get("sanitized_request") or {},
            upstream_id=value.get("upstream_id"),
            upstream_last_modified=value.get("upstream_last_modified"),
            etag=value.get("etag"),
            retry_count=int(value.get("retry_count", 0)),
            cache_hit=bool(value.get("cache_hit", False)),
            cache_key=value.get("cache_key"),
            content_sha256=value.get("content_sha256"),
            media_type=value.get("media_type"),
            error_code=value.get("error_code"),
            metadata=value.get("metadata") or {},
        )


def _deep_sorted_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively materialize mappings with sorted keys for determinism."""

    out: dict[str, Any] = {}
    for key in sorted(value.keys(), key=lambda k: str(k)):
        item = value[key]
        if isinstance(item, Mapping):
            out[str(key)] = _deep_sorted_mapping(item)
        elif isinstance(item, (list, tuple)):
            out[str(key)] = [
                _deep_sorted_mapping(v) if isinstance(v, Mapping) else v for v in item
            ]
        else:
            out[str(key)] = item
    return out


@dataclass(frozen=True, slots=True)
class AuthoritySourceRecord:
    """One authority-labeled source with optional dual identities.

    Connectors may attach both an official artifact identity (for example a
    GovInfo annual CFR PDF/XML) and a derived presentation identity (for
    example eCFR HTML for the same section). The two identities remain
    separate so presentation can never replace the official record.
    """

    source_key: str
    authority_tier: AuthorityTier
    collection: str
    jurisdiction: str = "US"
    title: Optional[str] = None
    citation: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    release_point: Optional[str] = None
    revision: Optional[str] = None
    date_issued: Optional[date] = None
    publication_date: Optional[date] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    termination_date: Optional[date] = None
    official_artifact: Optional[ArtifactIdentity] = None
    derived_presentation: Optional[ArtifactIdentity] = None
    receipt: Optional[SourceReceipt] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    signature_present: bool = False
    signature_valid: Optional[bool] = None
    signature_algorithm: Optional[str] = None
    signature_evidence: Optional[str] = None
    retry_cache_policy: RetryCachePolicy = field(default_factory=RetryCachePolicy)
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_key", _require_non_empty_str(self.source_key, "source_key")
        )
        object.__setattr__(self, "authority_tier", _coerce_authority_tier(self.authority_tier))
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        object.__setattr__(
            self, "jurisdiction", _require_non_empty_str(self.jurisdiction, "jurisdiction")
        )
        for name in ("title", "citation", "notes", "signature_algorithm", "signature_evidence"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))

        for name in ("edition", "version", "release_point", "revision"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(raw, name)
                reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)

        object.__setattr__(
            self, "date_issued", _parse_optional_date(self.date_issued, name="date_issued")
        )
        object.__setattr__(
            self,
            "publication_date",
            _parse_optional_date(self.publication_date, name="publication_date"),
        )
        object.__setattr__(
            self,
            "effective_start",
            _parse_optional_date(self.effective_start, name="effective_start"),
        )
        object.__setattr__(
            self,
            "effective_end",
            _parse_optional_date(self.effective_end, name="effective_end"),
        )
        object.__setattr__(
            self,
            "termination_date",
            _parse_optional_date(self.termination_date, name="termination_date"),
        )

        if self.effective_start and self.effective_end:
            if self.effective_end < self.effective_start:
                raise PatentAuthoritySourcesError(
                    "effective_end must be on or after effective_start"
                )

        if self.official_artifact is not None:
            if not isinstance(self.official_artifact, ArtifactIdentity):
                raise PatentAuthoritySourcesError(
                    "official_artifact must be an ArtifactIdentity"
                )
            if self.official_artifact.role is not IdentityRole.OFFICIAL_ARTIFACT:
                object.__setattr__(
                    self,
                    "official_artifact",
                    replace(self.official_artifact, role=IdentityRole.OFFICIAL_ARTIFACT),
                )
        if self.derived_presentation is not None:
            if not isinstance(self.derived_presentation, ArtifactIdentity):
                raise PatentAuthoritySourcesError(
                    "derived_presentation must be an ArtifactIdentity"
                )
            if self.derived_presentation.role is not IdentityRole.DERIVED_PRESENTATION:
                object.__setattr__(
                    self,
                    "derived_presentation",
                    replace(
                        self.derived_presentation,
                        role=IdentityRole.DERIVED_PRESENTATION,
                    ),
                )

        if self.receipt is not None and not isinstance(self.receipt, SourceReceipt):
            raise PatentAuthoritySourcesError("receipt must be a SourceReceipt")

        object.__setattr__(
            self,
            "verification_state",
            _coerce_verification_state(self.verification_state),
        )
        if not isinstance(self.retry_cache_policy, RetryCachePolicy):
            raise PatentAuthoritySourcesError("retry_cache_policy must be RetryCachePolicy")
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthoritySourcesError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        self._reject_latest_in_metadata(self.metadata)

        # Official tiers should carry an official artifact identity when recorded.
        if (
            self.authority_tier
            in (AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE)
            and self.official_artifact is None
            and self.derived_presentation is not None
        ):
            raise PatentAuthoritySourcesError(
                f"{self.authority_tier.value} sources must not use only a "
                "derived presentation identity; attach official_artifact"
            )

    @staticmethod
    def _reject_latest_in_metadata(metadata: Mapping[str, Any], *, prefix: str = "metadata") -> None:
        for key, value in metadata.items():
            path = f"{prefix}.{key}"
            key_l = str(key).lower()
            if key_l in _FORBIDDEN_IDENTITY_KEYS or key_l.endswith("_edition"):
                reject_hard_coded_latest(value, field_name=path)
            if isinstance(value, Mapping):
                AuthoritySourceRecord._reject_latest_in_metadata(value, prefix=path)

    def with_official_artifact(self, identity: ArtifactIdentity) -> "AuthoritySourceRecord":
        """Return a copy with *identity* recorded as the official artifact."""

        official = replace(identity, role=IdentityRole.OFFICIAL_ARTIFACT)
        return replace(self, official_artifact=official)

    def with_derived_presentation(self, identity: ArtifactIdentity) -> "AuthoritySourceRecord":
        """Return a copy with *identity* recorded as derived presentation."""

        derived = replace(identity, role=IdentityRole.DERIVED_PRESENTATION)
        return replace(self, derived_presentation=derived)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "collection": self.collection,
            "date_issued": _date_to_str(self.date_issued),
            "derived_presentation": (
                None
                if self.derived_presentation is None
                else self.derived_presentation.to_dict()
            ),
            "edition": self.edition,
            "effective_end": _date_to_str(self.effective_end),
            "effective_start": _date_to_str(self.effective_start),
            "jurisdiction": self.jurisdiction,
            "metadata": _deep_sorted_mapping(self.metadata),
            "notes": self.notes,
            "official_artifact": (
                None if self.official_artifact is None else self.official_artifact.to_dict()
            ),
            "publication_date": _date_to_str(self.publication_date),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "release_point": self.release_point,
            "retry_cache_policy": self.retry_cache_policy.to_dict(),
            "revision": self.revision,
            "schema_version": SCHEMA_VERSION,
            "signature_algorithm": self.signature_algorithm,
            "signature_evidence": self.signature_evidence,
            "signature_present": bool(self.signature_present),
            "signature_valid": self.signature_valid,
            "source_key": self.source_key,
            "termination_date": _date_to_str(self.termination_date),
            "title": self.title,
            "verification_state": self.verification_state.value,
            "version": self.version,
        }

    def to_canonical_json(self) -> str:
        """Deterministic JSON serialization for fixtures."""

        return canonical_json_dumps(self.to_dict())

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritySourceRecord":
        if not isinstance(value, Mapping):
            raise PatentAuthoritySourcesError("authority source record must be a mapping")
        if "authority_tier" not in value or value.get("authority_tier") in (None, ""):
            raise MissingAuthorityTierError("authority_tier is required")

        official_raw = value.get("official_artifact")
        derived_raw = value.get("derived_presentation")
        receipt_raw = value.get("receipt")
        policy_raw = value.get("retry_cache_policy")

        return cls(
            source_key=value["source_key"],
            authority_tier=value["authority_tier"],
            collection=value["collection"],
            jurisdiction=value.get("jurisdiction", "US"),
            title=value.get("title"),
            citation=value.get("citation"),
            edition=value.get("edition"),
            version=value.get("version"),
            release_point=value.get("release_point"),
            revision=value.get("revision"),
            date_issued=value.get("date_issued"),
            publication_date=value.get("publication_date"),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            termination_date=value.get("termination_date"),
            official_artifact=(
                None if official_raw is None else ArtifactIdentity.from_dict(official_raw)
            ),
            derived_presentation=(
                None if derived_raw is None else ArtifactIdentity.from_dict(derived_raw)
            ),
            receipt=None if receipt_raw is None else SourceReceipt.from_dict(receipt_raw),
            verification_state=value.get(
                "verification_state", VerificationState.UNVERIFIED
            ),
            signature_present=bool(value.get("signature_present", False)),
            signature_valid=value.get("signature_valid"),
            signature_algorithm=value.get("signature_algorithm"),
            signature_evidence=value.get("signature_evidence"),
            retry_cache_policy=RetryCachePolicy.from_dict(policy_raw),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


class AuthoritySourceRegistry:
    """In-memory registry of authority-labeled sources and their receipts.

    Registration is fail-closed:

    * missing :attr:`AuthoritySourceRecord.authority_tier` is rejected;
    * hard-coded ``latest`` edition/version tokens are rejected;
    * duplicate ``source_key`` values are rejected unless ``overwrite=True``.
    """

    def __init__(
        self,
        *,
        default_retry_cache_policy: RetryCachePolicy | None = None,
    ) -> None:
        self._default_retry_cache_policy = (
            default_retry_cache_policy
            if default_retry_cache_policy is not None
            else DEFAULT_RETRY_CACHE_POLICY
        )
        self._sources: dict[str, AuthoritySourceRecord] = {}
        self._receipts: dict[str, list[SourceReceipt]] = {}

    @property
    def default_retry_cache_policy(self) -> RetryCachePolicy:
        return self._default_retry_cache_policy

    def __len__(self) -> int:
        return len(self._sources)

    def __contains__(self, source_key: object) -> bool:
        return isinstance(source_key, str) and source_key in self._sources

    def __iter__(self) -> Iterator[AuthoritySourceRecord]:
        for key in sorted(self._sources):
            yield self._sources[key]

    def get(self, source_key: str) -> AuthoritySourceRecord:
        try:
            return self._sources[source_key]
        except KeyError as exc:
            raise AuthoritySourceRegistryError(
                f"unknown source_key: {source_key!r}"
            ) from exc

    def list_by_tier(self, tier: AuthorityTier | str) -> list[AuthoritySourceRecord]:
        resolved = _coerce_authority_tier(tier)
        return [record for record in self if record.authority_tier is resolved]

    def receipts_for(self, source_key: str) -> tuple[SourceReceipt, ...]:
        return tuple(self._receipts.get(source_key, ()))

    def register(
        self,
        record: AuthoritySourceRecord | Mapping[str, Any],
        *,
        overwrite: bool = False,
    ) -> AuthoritySourceRecord:
        """Validate and store an authority source record.

        Accepts a fully built :class:`AuthoritySourceRecord` or a mapping that
        is validated through :meth:`AuthoritySourceRecord.from_dict`.

        When *overwrite* is false (default), a duplicate ``source_key`` raises
        :class:`AuthoritySourceRegistryError`.
        """

        if isinstance(record, AuthoritySourceRecord):
            # Re-run construction path so validators fire even if the caller
            # bypassed __post_init__ via object.__new__ tricks.
            validated = AuthoritySourceRecord.from_dict(record.to_dict())
        elif isinstance(record, Mapping):
            if "authority_tier" not in record or record.get("authority_tier") in (None, ""):
                raise MissingAuthorityTierError("authority_tier is required")
            for name in ("edition", "version", "release_point", "revision"):
                if name in record:
                    reject_hard_coded_latest(record.get(name), field_name=name)
            validated = AuthoritySourceRecord.from_dict(record)
        else:
            raise PatentAuthoritySourcesError(
                "record must be AuthoritySourceRecord or mapping"
            )

        # Apply registry default policy when the record still has the generic default
        # and the registry was constructed with a custom default.
        if (
            validated.retry_cache_policy == DEFAULT_RETRY_CACHE_POLICY
            and self._default_retry_cache_policy != DEFAULT_RETRY_CACHE_POLICY
        ):
            validated = replace(
                validated, retry_cache_policy=self._default_retry_cache_policy
            )

        key = validated.source_key
        if key in self._sources and not overwrite:
            raise AuthoritySourceRegistryError(
                f"source_key already registered: {key!r}"
            )
        self._sources[key] = validated
        if validated.receipt is not None:
            self._receipts.setdefault(key, []).append(validated.receipt)
        return validated

    def attach_receipt(
        self,
        source_key: str,
        receipt: SourceReceipt | Mapping[str, Any],
    ) -> AuthoritySourceRecord:
        """Append a retrieval receipt and update the record's primary receipt."""

        current = self.get(source_key)
        typed = (
            receipt
            if isinstance(receipt, SourceReceipt)
            else SourceReceipt.from_dict(receipt)
        )
        updated = replace(current, receipt=typed)
        self._sources[source_key] = updated
        self._receipts.setdefault(source_key, []).append(typed)
        return updated

    def preserve_dual_identities(
        self,
        source_key: str,
        *,
        official_artifact: ArtifactIdentity | Mapping[str, Any] | None = None,
        derived_presentation: ArtifactIdentity | Mapping[str, Any] | None = None,
    ) -> AuthoritySourceRecord:
        """Update a source so both official and derived identities are retained."""

        current = self.get(source_key)
        official = current.official_artifact
        derived = current.derived_presentation
        if official_artifact is not None:
            identity = (
                official_artifact
                if isinstance(official_artifact, ArtifactIdentity)
                else ArtifactIdentity.from_dict(official_artifact)
            )
            official = replace(identity, role=IdentityRole.OFFICIAL_ARTIFACT)
        if derived_presentation is not None:
            identity = (
                derived_presentation
                if isinstance(derived_presentation, ArtifactIdentity)
                else ArtifactIdentity.from_dict(derived_presentation)
            )
            derived = replace(identity, role=IdentityRole.DERIVED_PRESENTATION)
        if official is None and derived is None:
            raise PatentAuthoritySourcesError(
                "at least one of official_artifact or derived_presentation is required"
            )
        updated = replace(
            current,
            official_artifact=official,
            derived_presentation=derived,
        )
        # Re-validate dual-identity invariants for official tiers.
        updated = AuthoritySourceRecord.from_dict(updated.to_dict())
        self._sources[source_key] = updated
        return updated

    def to_fixture_dict(self) -> dict[str, Any]:
        """Serialize the full registry to a deterministic fixture payload."""

        sources = [record.to_dict() for record in self]
        receipt_index: dict[str, list[dict[str, Any]]] = {}
        for key in sorted(self._receipts):
            receipt_index[key] = [r.to_dict() for r in self._receipts[key]]
        return {
            "default_retry_cache_policy": self._default_retry_cache_policy.to_dict(),
            "receipt_index": receipt_index,
            "schema_version": SCHEMA_VERSION,
            "sources": sources,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_fixture_dict())

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_fixture_dict())

    @classmethod
    def from_fixture_dict(cls, value: Mapping[str, Any]) -> "AuthoritySourceRegistry":
        if not isinstance(value, Mapping):
            raise PatentAuthoritySourcesError("fixture payload must be a mapping")
        policy = RetryCachePolicy.from_dict(value.get("default_retry_cache_policy"))
        registry = cls(default_retry_cache_policy=policy)
        for item in value.get("sources") or []:
            registry.register(item, overwrite=True)
        # Restore full receipt history when present.
        receipt_index = value.get("receipt_index") or {}
        if isinstance(receipt_index, Mapping):
            for key, items in receipt_index.items():
                if key not in registry:
                    continue
                history: list[SourceReceipt] = []
                for raw in items or []:
                    history.append(SourceReceipt.from_dict(raw))
                registry._receipts[str(key)] = history
        return registry

    @classmethod
    def from_canonical_json(cls, text: str | bytes) -> "AuthoritySourceRegistry":
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise PatentAuthoritySourcesError("canonical JSON must decode to a mapping")
        return cls.from_fixture_dict(payload)


def build_fixture_record(
    *,
    source_key: str,
    authority_tier: AuthorityTier | str,
    collection: str,
    edition: str,
    official_sha256: str,
    official_url: str,
    provider: str,
    derived_sha256: str | None = None,
    derived_url: str | None = None,
    retrieved_at: str | datetime = "2024-06-01T12:00:00Z",
    response_status: int = 200,
    **kwargs: Any,
) -> AuthoritySourceRecord:
    """Convenience builder for deterministic unit-test and connector fixtures."""

    official = ArtifactIdentity(
        provider=provider,
        source_id=f"{source_key}:official",
        artifact_sha256=official_sha256,
        source_url=official_url,
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )
    derived = None
    if derived_sha256 is not None and derived_url is not None:
        derived = ArtifactIdentity(
            provider=provider,
            source_id=f"{source_key}:derived",
            artifact_sha256=derived_sha256,
            source_url=derived_url,
            role=IdentityRole.DERIVED_PRESENTATION,
        )
    receipt = SourceReceipt(
        endpoint=official_url,
        retrieved_at=retrieved_at,
        response_status=response_status,
        sanitized_request={"method": "GET", "path": official_url},
        content_sha256=official_sha256,
        retry_count=0,
        cache_hit=False,
    )
    return AuthoritySourceRecord(
        source_key=source_key,
        authority_tier=authority_tier,
        collection=collection,
        edition=edition,
        official_artifact=official,
        derived_presentation=derived,
        receipt=receipt,
        **kwargs,
    )


__all__ = [
    "SCHEMA_VERSION",
    "AuthoritySourceRecord",
    "AuthoritySourceRegistry",
    "AuthoritySourceRegistryError",
    "AuthorityTier",
    "ArtifactIdentity",
    "DEFAULT_RETRY_CACHE_POLICY",
    "HardCodedLatestEditionError",
    "IdentityRole",
    "MissingAuthorityTierError",
    "PatentAuthoritySourcesError",
    "RetryCachePolicy",
    "SourceReceipt",
    "VerificationState",
    "build_fixture_record",
    "canonical_json_bytes",
    "canonical_json_dumps",
    "reject_hard_coded_latest",
]
