"""State-law official-source authority catalog and admission policy (LCR-002).

Defines the exact 51-jurisdiction set (50 postal state codes + DC), loads the
sealed official-source catalog, and fail-closes corpus admission when:

* the jurisdiction set is not exactly the sealed 51 codes;
* a jurisdiction lacks at least one authoritative acquisition path;
* admission is attempted with only secondary/mutable sources;
* release/edition pins use mutable tokens such as ``latest`` / ``main`` / ``HEAD``.

Live network I/O is out of scope; this module is offline catalog + policy only.
Downstream scrapers consume cataloged entry URLs and domain constraints.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-source-policy-v1"
CATALOG_SCHEMA_VERSION: Final = "state-laws-official-source-catalog-v1"
TASK_ID: Final = "LCR-002"
EXPECTED_JURISDICTION_COUNT: Final = 51

# Exact jurisdiction set: 50 postal state codes + DC (no extras, no omissions).
CANONICAL_JURISDICTIONS: Final = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

CANONICAL_JURISDICTION_NAMES: Final = MappingProxyType(
    {
        "AL": "Alabama",
        "AK": "Alaska",
        "AZ": "Arizona",
        "AR": "Arkansas",
        "CA": "California",
        "CO": "Colorado",
        "CT": "Connecticut",
        "DE": "Delaware",
        "DC": "District of Columbia",
        "FL": "Florida",
        "GA": "Georgia",
        "HI": "Hawaii",
        "ID": "Idaho",
        "IL": "Illinois",
        "IN": "Indiana",
        "IA": "Iowa",
        "KS": "Kansas",
        "KY": "Kentucky",
        "LA": "Louisiana",
        "ME": "Maine",
        "MD": "Maryland",
        "MA": "Massachusetts",
        "MI": "Michigan",
        "MN": "Minnesota",
        "MS": "Mississippi",
        "MO": "Missouri",
        "MT": "Montana",
        "NE": "Nebraska",
        "NV": "Nevada",
        "NH": "New Hampshire",
        "NJ": "New Jersey",
        "NM": "New Mexico",
        "NY": "New York",
        "NC": "North Carolina",
        "ND": "North Dakota",
        "OH": "Ohio",
        "OK": "Oklahoma",
        "OR": "Oregon",
        "PA": "Pennsylvania",
        "RI": "Rhode Island",
        "SC": "South Carolina",
        "SD": "South Dakota",
        "TN": "Tennessee",
        "TX": "Texas",
        "UT": "Utah",
        "VT": "Vermont",
        "VA": "Virginia",
        "WA": "Washington",
        "WV": "West Virginia",
        "WI": "Wisconsin",
        "WY": "Wyoming",
    }
)

# Relative to repository root (parents[3] of this file).
DEFAULT_CATALOG_RELATIVE_PATH: Final = Path("data/legal/state_laws/official_source_catalog.json")

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was "
    "retrieved or sealed; they are not a claim that the codified text is "
    "legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official source."
)

# Host markers that are always secondary (quarantine by default).
SECONDARY_HOST_MARKERS: Final = frozenset(
    {
        "law.justia.com",
        "codes.findlaw.com",
        "www.findlaw.com",
        "lp.findlaw.com",
        "casetext.com",
        "www.casetext.com",
        "law.cornell.edu",
        "www.law.cornell.edu",
        "en.wikipedia.org",
        "wikipedia.org",
        "www.wikipedia.org",
        "lexisnexis.com",
        "www.lexisnexis.com",
        "advance.lexis.com",
        "westlaw.com",
        "www.westlaw.com",
        "1.next.westlaw.com",
        "bloomberglaw.com",
        "www.bloomberglaw.com",
        "fastcase.com",
        "www.fastcase.com",
        "casemakerlegal.com",
        "www.casemakerlegal.com",
    }
)

_MUTABLE_TOKEN_RE = re.compile(
    r"^(?:latest|main|master|HEAD|tip|trunk|default-branch)$",
    re.IGNORECASE,
)
_MUTABLE_TOKEN_IN_PATH_RE = re.compile(
    r"(?:^|[/@:])(?:latest|main|master|HEAD)(?:$|[/@:])",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POSTAL_CODE_RE = re.compile(r"^[A-Z]{2}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsSourcePolicyError(ValueError):
    """Base error for state-law source authority policy failures."""


class JurisdictionSetError(StateLawsSourcePolicyError):
    """Raised when the jurisdiction set is not exactly the 51-code constant."""


class CatalogSchemaError(StateLawsSourcePolicyError):
    """Raised when the official-source catalog is missing or malformed."""


class MissingAuthoritativePathError(StateLawsSourcePolicyError):
    """Raised when a jurisdiction lacks an authoritative acquisition path."""


class SecondaryOnlyAdmissionError(StateLawsSourcePolicyError):
    """Raised when admission is attempted with only secondary sources."""


class MutableReferenceError(StateLawsSourcePolicyError):
    """Raised when a release/edition pin uses a mutable token."""


class DomainConstraintError(StateLawsSourcePolicyError):
    """Raised when a URL violates catalog domain constraints."""


class AuthorityExceptionError(StateLawsSourcePolicyError):
    """Raised when an authority exception is incomplete or unapproved."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceRole(str, Enum):
    """Role of one acquisition path relative to official authority."""

    OFFICIAL_LEGISLATURE = "official_legislature"
    OFFICIAL_REVISER = "official_reviser"
    OFFICIAL_CODE_PUBLISHER = "official_code_publisher"
    DC_COUNCIL = "dc_council"
    SECONDARY = "secondary"
    EXCEPTION = "exception"

    @classmethod
    def coerce(cls, value: Any) -> "SourceRole":
        if isinstance(value, SourceRole):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "legislature": cls.OFFICIAL_LEGISLATURE,
            "official": cls.OFFICIAL_LEGISLATURE,
            "primary": cls.OFFICIAL_LEGISLATURE,
            "reviser": cls.OFFICIAL_REVISER,
            "code_publisher": cls.OFFICIAL_CODE_PUBLISHER,
            "publisher": cls.OFFICIAL_CODE_PUBLISHER,
            "dc": cls.DC_COUNCIL,
            "district_of_columbia": cls.DC_COUNCIL,
            "council": cls.DC_COUNCIL,
            "secondary_mirror": cls.SECONDARY,
            "quarantine": cls.SECONDARY,
            "approved_exception": cls.EXCEPTION,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsSourcePolicyError(f"unknown source role: {value!r}")


class AuthorityClass(str, Enum):
    """Whether a path is official authority, secondary, or documented exception."""

    OFFICIAL = "official"
    SECONDARY = "secondary"
    EXCEPTION = "exception"

    @classmethod
    def coerce(cls, value: Any) -> "AuthorityClass":
        if isinstance(value, AuthorityClass):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "primary": cls.OFFICIAL,
            "legislature": cls.OFFICIAL,
            "code_publisher": cls.OFFICIAL,
            "reviser": cls.OFFICIAL,
            "dc_council": cls.OFFICIAL,
            "approved_exception": cls.EXCEPTION,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsSourcePolicyError(f"unknown authority class: {value!r}")


class DiscoveryMode(str, Enum):
    """How hierarchy / bundle discovery is expected to proceed."""

    HIERARCHY = "hierarchy"
    BUNDLE = "bundle"
    PAGINATED_INDEX = "paginated_index"
    API = "api"
    MIXED = "mixed"

    @classmethod
    def coerce(cls, value: Any) -> "DiscoveryMode":
        if isinstance(value, DiscoveryMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "toc": cls.HIERARCHY,
            "tree": cls.HIERARCHY,
            "zip": cls.BUNDLE,
            "download": cls.BUNDLE,
            "pagination": cls.PAGINATED_INDEX,
            "index": cls.PAGINATED_INDEX,
            "graphql": cls.API,
            "rest": cls.API,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsSourcePolicyError(f"unknown discovery mode: {value!r}")


# Roles that satisfy the "at least one authoritative path" gate.
AUTHORITATIVE_ROLES: Final = frozenset(
    {
        SourceRole.OFFICIAL_LEGISLATURE,
        SourceRole.OFFICIAL_REVISER,
        SourceRole.OFFICIAL_CODE_PUBLISHER,
        SourceRole.DC_COUNCIL,
    }
)

AUTHORITATIVE_AUTHORITY_CLASSES: Final = frozenset(
    {
        AuthorityClass.OFFICIAL,
        AuthorityClass.EXCEPTION,
    }
)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsSourcePolicyError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsSourcePolicyError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise StateLawsSourcePolicyError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_http_url(value: Any, name: str) -> str:
    text = _require_non_empty_str(value, name, maximum=2048)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StateLawsSourcePolicyError(f"{name} must be an absolute http(s) URL")
    return text


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _normalize_domain(value: Any, name: str = "domain") -> str:
    text = _require_non_empty_str(value, name, maximum=253).lower()
    if text.startswith("."):
        text = text[1:]
    if "/" in text or ":" in text or " " in text:
        raise StateLawsSourcePolicyError(f"{name} must be a bare hostname: {value!r}")
    return text


def is_secondary_host(host: str) -> bool:
    """Return True when *host* is a known secondary/commercial mirror."""

    h = (host or "").lower().strip(".")
    if not h:
        return False
    if h in SECONDARY_HOST_MARKERS:
        return True
    return any(h == marker or h.endswith("." + marker) for marker in SECONDARY_HOST_MARKERS)


def is_mutable_reference(value: Any) -> bool:
    """Return True when *value* is a hard-coded mutable pin token."""

    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if _MUTABLE_TOKEN_RE.fullmatch(text):
        return True
    # Path-shaped mutable pins (e.g. "branch/latest", "refs/heads/main").
    if _MUTABLE_TOKEN_IN_PATH_RE.search(text):
        return True
    return False


def reject_mutable_reference(value: Any, *, field_name: str) -> None:
    """Fail closed when *value* is a mutable release/edition/branch pin."""

    if is_mutable_reference(value):
        raise MutableReferenceError(
            f"{field_name} must not be a mutable pin ({value!r}); "
            "record a concrete edition, release point, or content digest"
        )


def normalize_postal_code(value: Any, *, name: str = "postal_code") -> str:
    """Normalize and validate a postal jurisdiction code against the exact 51-set."""

    text = _require_non_empty_str(value, name, maximum=8).upper()
    if not _POSTAL_CODE_RE.fullmatch(text):
        raise JurisdictionSetError(f"{name}={text!r} is not a two-letter postal code")
    if text not in CANONICAL_JURISDICTIONS:
        raise JurisdictionSetError(
            f"{name}={text!r} is not in the exact 51-jurisdiction set "
            f"(expected {EXPECTED_JURISDICTION_COUNT} codes including DC)"
        )
    return text


def validate_jurisdiction_set(
    codes: Iterable[Any],
    *,
    name: str = "jurisdictions",
) -> tuple[str, ...]:
    """Require the exact 51-jurisdiction set (no missing, no extra, no dupes)."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = normalize_postal_code(raw, name=name)
        if code in seen:
            raise JurisdictionSetError(f"{name} contains duplicate postal code {code!r}")
        seen.add(code)
        normalized.append(code)
    actual = frozenset(normalized)
    if actual != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - actual)
        extra = sorted(actual - CANONICAL_JURISDICTIONS)
        raise JurisdictionSetError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    if len(normalized) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionSetError(
            f"{name} must contain exactly {EXPECTED_JURISDICTION_COUNT} unique codes, "
            f"got {len(normalized)}"
        )
    return tuple(sorted(normalized))


def repository_root() -> Path:
    """Return the repository root that contains ``data/legal/state_laws``."""

    return Path(__file__).resolve().parents[3]


def default_catalog_path() -> Path:
    """Return the default on-disk path of the sealed official-source catalog."""

    return repository_root() / DEFAULT_CATALOG_RELATIVE_PATH


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegatedInventoryPath:
    """State-delegated inventory authority that cannot admit document bodies."""

    path_id: str
    provider: str
    delegating_authority_url: str
    public_entry_url: str
    container_url: str
    allowed_domains: tuple[str, ...]
    discovery_mode: DiscoveryMode
    authority_scope: str = "toc_inventory_only"
    body_admissible: bool = False
    full_corpus_admissible: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path_id": self.path_id,
            "provider": self.provider,
            "delegating_authority_url": self.delegating_authority_url,
            "public_entry_url": self.public_entry_url,
            "container_url": self.container_url,
            "allowed_domains": list(self.allowed_domains),
            "discovery_mode": self.discovery_mode.value,
            "authority_scope": self.authority_scope,
            "body_admissible": self.body_admissible,
            "full_corpus_admissible": self.full_corpus_admissible,
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload

    @classmethod
    def from_mapping(
        cls,
        value: JsonMapping,
        *,
        context: str,
        delegating_domains: Sequence[str],
    ) -> DelegatedInventoryPath:
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        authority_scope = _require_non_empty_str(
            value.get("authority_scope"), f"{context}.authority_scope", maximum=64
        )
        if authority_scope != "toc_inventory_only":
            raise CatalogSchemaError(
                f"{context}.authority_scope must be 'toc_inventory_only'"
            )
        if value.get("body_admissible") is not False:
            raise CatalogSchemaError(f"{context}.body_admissible must be false")
        if value.get("full_corpus_admissible") is not False:
            raise CatalogSchemaError(f"{context}.full_corpus_admissible must be false")

        delegating_url = _require_http_url(
            value.get("delegating_authority_url"),
            f"{context}.delegating_authority_url",
        )
        public_entry_url = _require_http_url(
            value.get("public_entry_url"), f"{context}.public_entry_url"
        )
        container_url = _require_http_url(
            value.get("container_url"), f"{context}.container_url"
        )
        for name, url in (
            ("delegating_authority_url", delegating_url),
            ("public_entry_url", public_entry_url),
            ("container_url", container_url),
        ):
            if urlparse(url).scheme != "https":
                raise CatalogSchemaError(f"{context}.{name} must use https")

        raw_domains = value.get("allowed_domains") or []
        if not isinstance(raw_domains, Sequence) or isinstance(
            raw_domains, (str, bytes)
        ):
            raise CatalogSchemaError(
                f"{context}.allowed_domains must be a list of hostnames"
            )
        domains = tuple(
            _normalize_domain(item, f"{context}.allowed_domains")
            for item in raw_domains
        )
        if not domains:
            raise CatalogSchemaError(f"{context}.allowed_domains must be non-empty")

        delegating_host = _host_of(delegating_url)
        if is_secondary_host(delegating_host) or not any(
            delegating_host == domain or delegating_host.endswith("." + domain)
            for domain in delegating_domains
        ):
            raise DomainConstraintError(
                f"{context}.delegating_authority_url is outside the parent official path"
            )
        for name, url in (
            ("public_entry_url", public_entry_url),
            ("container_url", container_url),
        ):
            host = _host_of(url)
            if not any(
                host == domain or host.endswith("." + domain) for domain in domains
            ):
                raise DomainConstraintError(
                    f"{context}.{name} host {host!r} is outside "
                    f"allowed_domains={list(domains)!r}"
                )

        return cls(
            path_id=_require_non_empty_str(
                value.get("path_id"), f"{context}.path_id", maximum=128
            ),
            provider=_require_non_empty_str(
                value.get("provider"), f"{context}.provider", maximum=128
            ),
            delegating_authority_url=delegating_url,
            public_entry_url=public_entry_url,
            container_url=container_url,
            allowed_domains=domains,
            discovery_mode=DiscoveryMode.coerce(value.get("discovery_mode")),
            authority_scope=authority_scope,
            body_admissible=False,
            full_corpus_admissible=False,
            notes=str(value.get("notes") or "").strip(),
        )


@dataclass(frozen=True)
class AcquisitionPath:
    """One cataloged acquisition path for a jurisdiction."""

    path_id: str
    role: SourceRole
    authority_class: AuthorityClass
    provider: str
    base_url: str
    entry_url: str
    allowed_domains: tuple[str, ...]
    discovery_mode: DiscoveryMode
    as_of_fields: tuple[str, ...] = ("edition", "publication_date", "retrieval_time")
    notes: str = ""
    exception_id: Optional[str] = None
    exception_rationale: Optional[str] = None
    delegated_inventory: Optional[DelegatedInventoryPath] = None

    def is_authoritative(self) -> bool:
        """Return True when this path may authorize corpus admission."""

        if self.authority_class is AuthorityClass.SECONDARY:
            return False
        if self.role is SourceRole.SECONDARY:
            return False
        if self.authority_class is AuthorityClass.EXCEPTION:
            return bool(self.exception_id and self.exception_rationale)
        return self.role in AUTHORITATIVE_ROLES

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path_id": self.path_id,
            "role": self.role.value,
            "authority_class": self.authority_class.value,
            "provider": self.provider,
            "base_url": self.base_url,
            "entry_url": self.entry_url,
            "allowed_domains": list(self.allowed_domains),
            "discovery_mode": self.discovery_mode.value,
            "as_of_fields": list(self.as_of_fields),
        }
        if self.notes:
            payload["notes"] = self.notes
        if self.exception_id:
            payload["exception_id"] = self.exception_id
        if self.exception_rationale:
            payload["exception_rationale"] = self.exception_rationale
        if self.delegated_inventory is not None:
            payload["delegated_inventory"] = self.delegated_inventory.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "acquisition_path") -> "AcquisitionPath":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        path_id = _require_non_empty_str(value.get("path_id"), f"{context}.path_id", maximum=128)
        role = SourceRole.coerce(value.get("role"))
        authority = AuthorityClass.coerce(
            value.get("authority_class", AuthorityClass.OFFICIAL.value)
        )
        provider = _require_non_empty_str(value.get("provider"), f"{context}.provider", maximum=128)
        base_url = _require_http_url(value.get("base_url"), f"{context}.base_url")
        entry_url = _require_http_url(value.get("entry_url"), f"{context}.entry_url")
        raw_domains = value.get("allowed_domains") or []
        if not isinstance(raw_domains, Sequence) or isinstance(raw_domains, (str, bytes)):
            raise CatalogSchemaError(f"{context}.allowed_domains must be a list of hostnames")
        domains = tuple(_normalize_domain(d, f"{context}.allowed_domains") for d in raw_domains)
        if not domains:
            raise CatalogSchemaError(f"{context}.allowed_domains must be non-empty")
        discovery = DiscoveryMode.coerce(value.get("discovery_mode", DiscoveryMode.HIERARCHY.value))
        raw_as_of = value.get("as_of_fields") or (
            "edition",
            "publication_date",
            "retrieval_time",
        )
        if not isinstance(raw_as_of, Sequence) or isinstance(raw_as_of, (str, bytes)):
            raise CatalogSchemaError(f"{context}.as_of_fields must be a list of field names")
        as_of_fields = tuple(
            _require_non_empty_str(item, f"{context}.as_of_fields", maximum=64) for item in raw_as_of
        )
        if not as_of_fields:
            raise CatalogSchemaError(f"{context}.as_of_fields must be non-empty")
        notes = str(value.get("notes") or "").strip()
        exception_id = value.get("exception_id")
        exception_rationale = value.get("exception_rationale")
        if exception_id is not None:
            exception_id = _require_non_empty_str(exception_id, f"{context}.exception_id", maximum=128)
        if exception_rationale is not None:
            exception_rationale = _require_non_empty_str(
                exception_rationale, f"{context}.exception_rationale", maximum=2048
            )
        delegated_raw = value.get("delegated_inventory")
        delegated_inventory = (
            None
            if delegated_raw is None
            else DelegatedInventoryPath.from_mapping(
                delegated_raw,
                context=f"{context}.delegated_inventory",
                delegating_domains=domains,
            )
        )

        # Domain constraints: entry host must be allowed; secondary hosts cannot be official.
        entry_host = _host_of(entry_url)
        base_host = _host_of(base_url)
        if not any(entry_host == d or entry_host.endswith("." + d) for d in domains):
            raise DomainConstraintError(
                f"{context}.entry_url host {entry_host!r} is outside allowed_domains={list(domains)!r}"
            )
        if not any(base_host == d or base_host.endswith("." + d) for d in domains):
            raise DomainConstraintError(
                f"{context}.base_url host {base_host!r} is outside allowed_domains={list(domains)!r}"
            )
        if is_secondary_host(entry_host) or is_secondary_host(base_host):
            if authority is not AuthorityClass.SECONDARY or role is not SourceRole.SECONDARY:
                raise DomainConstraintError(
                    f"{context} uses secondary host {entry_host or base_host!r} but is not "
                    "classified as secondary"
                )
        if authority is AuthorityClass.EXCEPTION or role is SourceRole.EXCEPTION:
            if not exception_id or not exception_rationale:
                raise AuthorityExceptionError(
                    f"{context} exception paths require exception_id and exception_rationale"
                )
        if authority is AuthorityClass.OFFICIAL and role is SourceRole.SECONDARY:
            raise CatalogSchemaError(
                f"{context} cannot combine authority_class=official with role=secondary"
            )
        if authority is AuthorityClass.SECONDARY and role in AUTHORITATIVE_ROLES:
            raise CatalogSchemaError(
                f"{context} cannot combine authority_class=secondary with authoritative role"
            )

        return cls(
            path_id=path_id,
            role=role,
            authority_class=authority,
            provider=provider,
            base_url=base_url,
            entry_url=entry_url,
            allowed_domains=domains,
            discovery_mode=discovery,
            as_of_fields=as_of_fields,
            notes=notes,
            exception_id=exception_id,
            exception_rationale=exception_rationale,
            delegated_inventory=delegated_inventory,
        )


@dataclass(frozen=True)
class CodeFamily:
    """One official code family (e.g. Revised Statutes) for a jurisdiction."""

    code_family_id: str
    display_name: str
    citation_prefix: str
    hierarchy: tuple[str, ...]
    bundle_discovery: str = "html_toc"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_family_id": self.code_family_id,
            "display_name": self.display_name,
            "citation_prefix": self.citation_prefix,
            "hierarchy": list(self.hierarchy),
            "bundle_discovery": self.bundle_discovery,
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "code_family") -> "CodeFamily":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        hierarchy_raw = value.get("hierarchy") or ("title", "chapter", "section")
        if not isinstance(hierarchy_raw, Sequence) or isinstance(hierarchy_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.hierarchy must be a list")
        hierarchy = tuple(
            _require_non_empty_str(item, f"{context}.hierarchy", maximum=64) for item in hierarchy_raw
        )
        if not hierarchy:
            raise CatalogSchemaError(f"{context}.hierarchy must be non-empty")
        return cls(
            code_family_id=_require_non_empty_str(
                value.get("code_family_id"), f"{context}.code_family_id", maximum=128
            ),
            display_name=_require_non_empty_str(
                value.get("display_name"), f"{context}.display_name", maximum=256
            ),
            citation_prefix=_require_non_empty_str(
                value.get("citation_prefix"), f"{context}.citation_prefix", maximum=64
            ),
            hierarchy=hierarchy,
            bundle_discovery=_require_non_empty_str(
                value.get("bundle_discovery", "html_toc"),
                f"{context}.bundle_discovery",
                maximum=128,
            ),
        )


@dataclass(frozen=True)
class JurisdictionSourceRecord:
    """Catalog record for one of the exact 51 jurisdictions."""

    postal_code: str
    name: str
    code_families: tuple[CodeFamily, ...]
    acquisition_paths: tuple[AcquisitionPath, ...]
    domain_constraints: Mapping[str, Any] = field(default_factory=dict)
    authority_exceptions: tuple[Mapping[str, Any], ...] = ()

    def authoritative_paths(self) -> tuple[AcquisitionPath, ...]:
        return tuple(path for path in self.acquisition_paths if path.is_authoritative())

    def to_dict(self) -> dict[str, Any]:
        return {
            "postal_code": self.postal_code,
            "name": self.name,
            "code_families": [family.to_dict() for family in self.code_families],
            "acquisition_paths": [path.to_dict() for path in self.acquisition_paths],
            "domain_constraints": dict(self.domain_constraints),
            "authority_exceptions": [dict(item) for item in self.authority_exceptions],
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "jurisdiction"
    ) -> "JurisdictionSourceRecord":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError(f"{context} must be a mapping")
        postal = normalize_postal_code(value.get("postal_code"), name=f"{context}.postal_code")
        expected_name = CANONICAL_JURISDICTION_NAMES[postal]
        name = _require_non_empty_str(value.get("name"), f"{context}.name", maximum=128)
        if name != expected_name:
            raise CatalogSchemaError(
                f"{context}.name for {postal} must be {expected_name!r}, got {name!r}"
            )
        families_raw = value.get("code_families") or []
        if not isinstance(families_raw, Sequence) or isinstance(families_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.code_families must be a list")
        if not families_raw:
            raise CatalogSchemaError(f"{context}.code_families must be non-empty")
        families = tuple(
            CodeFamily.from_mapping(item, context=f"{context}.code_families[{idx}]")
            for idx, item in enumerate(families_raw)
        )
        paths_raw = value.get("acquisition_paths") or []
        if not isinstance(paths_raw, Sequence) or isinstance(paths_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.acquisition_paths must be a list")
        if not paths_raw:
            raise CatalogSchemaError(f"{context}.acquisition_paths must be non-empty")
        paths = tuple(
            AcquisitionPath.from_mapping(item, context=f"{context}.acquisition_paths[{idx}]")
            for idx, item in enumerate(paths_raw)
        )
        path_ids = [path.path_id for path in paths]
        if len(path_ids) != len(set(path_ids)):
            raise CatalogSchemaError(f"{context}.acquisition_paths path_id values must be unique")
        if not any(path.is_authoritative() for path in paths):
            raise MissingAuthoritativePathError(
                f"{context} ({postal}) must include at least one authoritative acquisition path"
            )
        constraints = value.get("domain_constraints") or {}
        if not isinstance(constraints, Mapping):
            raise CatalogSchemaError(f"{context}.domain_constraints must be a mapping")
        exceptions_raw = value.get("authority_exceptions") or []
        if not isinstance(exceptions_raw, Sequence) or isinstance(exceptions_raw, (str, bytes)):
            raise CatalogSchemaError(f"{context}.authority_exceptions must be a list")
        exceptions: list[Mapping[str, Any]] = []
        for idx, item in enumerate(exceptions_raw):
            if not isinstance(item, Mapping):
                raise CatalogSchemaError(
                    f"{context}.authority_exceptions[{idx}] must be a mapping"
                )
            exception_id = _require_non_empty_str(
                item.get("exception_id"),
                f"{context}.authority_exceptions[{idx}].exception_id",
                maximum=128,
            )
            rationale = _require_non_empty_str(
                item.get("rationale"),
                f"{context}.authority_exceptions[{idx}].rationale",
                maximum=2048,
            )
            approved_by = _require_non_empty_str(
                item.get("approved_by"),
                f"{context}.authority_exceptions[{idx}].approved_by",
                maximum=128,
            )
            exceptions.append(
                MappingProxyType(
                    {
                        "exception_id": exception_id,
                        "rationale": rationale,
                        "approved_by": approved_by,
                    }
                )
            )
        return cls(
            postal_code=postal,
            name=name,
            code_families=families,
            acquisition_paths=paths,
            domain_constraints=MappingProxyType(dict(constraints)),
            authority_exceptions=tuple(exceptions),
        )


@dataclass(frozen=True)
class OfficialSourceCatalog:
    """Sealed catalog of authoritative sources for all 51 jurisdictions."""

    schema_version: str
    task_id: str
    jurisdiction_count: int
    jurisdictions: tuple[JurisdictionSourceRecord, ...]
    description: str = ""
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER

    def postal_codes(self) -> tuple[str, ...]:
        return tuple(record.postal_code for record in self.jurisdictions)

    def get(self, postal_code: Any) -> JurisdictionSourceRecord:
        code = normalize_postal_code(postal_code)
        for record in self.jurisdictions:
            if record.postal_code == code:
                return record
        raise JurisdictionSetError(f"postal code {code!r} missing from catalog")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "description": self.description,
            "jurisdiction_count": self.jurisdiction_count,
            "currentness_disclaimer": self.currentness_disclaimer,
            "jurisdictions": [record.to_dict() for record in self.jurisdictions],
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping) -> "OfficialSourceCatalog":
        if not isinstance(value, Mapping):
            raise CatalogSchemaError("catalog root must be a mapping")
        schema_version = _require_non_empty_str(
            value.get("schema_version"), "schema_version", maximum=128
        )
        if schema_version != CATALOG_SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"schema_version must be {CATALOG_SCHEMA_VERSION!r}, got {schema_version!r}"
            )
        task_id = _require_non_empty_str(value.get("task_id"), "task_id", maximum=32)
        if task_id != TASK_ID:
            raise CatalogSchemaError(f"task_id must be {TASK_ID!r}, got {task_id!r}")
        jurisdiction_count = value.get("jurisdiction_count")
        if jurisdiction_count != EXPECTED_JURISDICTION_COUNT:
            raise CatalogSchemaError(
                f"jurisdiction_count must be {EXPECTED_JURISDICTION_COUNT}, "
                f"got {jurisdiction_count!r}"
            )
        rows = value.get("jurisdictions")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise CatalogSchemaError("jurisdictions must be a list")
        if len(rows) != EXPECTED_JURISDICTION_COUNT:
            raise CatalogSchemaError(
                f"jurisdictions must contain exactly {EXPECTED_JURISDICTION_COUNT} records, "
                f"got {len(rows)}"
            )
        records = tuple(
            JurisdictionSourceRecord.from_mapping(row, context=f"jurisdictions[{idx}]")
            for idx, row in enumerate(rows)
        )
        validate_jurisdiction_set(record.postal_code for record in records)
        description = str(value.get("description") or "").strip()
        disclaimer = str(value.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER).strip()
        return cls(
            schema_version=schema_version,
            task_id=task_id,
            jurisdiction_count=EXPECTED_JURISDICTION_COUNT,
            jurisdictions=tuple(sorted(records, key=lambda r: r.postal_code)),
            description=description,
            currentness_disclaimer=disclaimer,
        )


# ---------------------------------------------------------------------------
# Catalog load / validation
# ---------------------------------------------------------------------------


def load_official_source_catalog(
    path: Optional[PathLike] = None,
    *,
    payload: Optional[JsonMapping] = None,
) -> OfficialSourceCatalog:
    """Load and validate the sealed official-source catalog.

    Provide either *path* (default: repository catalog) or an in-memory
    *payload* mapping for tests.
    """

    if payload is not None and path is not None:
        raise StateLawsSourcePolicyError("provide path or payload, not both")
    if payload is not None:
        if not isinstance(payload, Mapping):
            raise CatalogSchemaError("payload must be a mapping")
        return OfficialSourceCatalog.from_mapping(payload)
    catalog_path = Path(path) if path is not None else default_catalog_path()
    if not catalog_path.is_file():
        raise CatalogSchemaError(f"official source catalog not found: {catalog_path}")
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogSchemaError(f"catalog JSON is invalid: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise CatalogSchemaError("catalog root must be a JSON object")
    return OfficialSourceCatalog.from_mapping(raw)


@lru_cache(maxsize=4)
def _cached_default_catalog(path_str: str) -> OfficialSourceCatalog:
    return load_official_source_catalog(path_str)


def get_official_source_catalog(
    path: Optional[PathLike] = None,
) -> OfficialSourceCatalog:
    """Return the validated default catalog (cached by absolute path)."""

    catalog_path = Path(path) if path is not None else default_catalog_path()
    return _cached_default_catalog(str(catalog_path.resolve()))


def clear_catalog_cache() -> None:
    """Clear the process-local catalog cache (for tests)."""

    _cached_default_catalog.cache_clear()


# ---------------------------------------------------------------------------
# Admission policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmissionRequest:
    """Request to admit material under the official-source policy."""

    postal_code: str
    acquisition_path_ids: tuple[str, ...]
    release_point: Optional[str] = None
    edition: Optional[str] = None
    as_of: Optional[str] = None
    source_url: Optional[str] = None
    authority_class: Optional[AuthorityClass] = None
    allow_secondary_quarantine: bool = False


@dataclass(frozen=True)
class AdmissionDecision:
    """Fail-closed admission outcome for one jurisdiction acquisition."""

    admitted: bool
    postal_code: str
    authoritative_path_ids: tuple[str, ...]
    reason: str
    quarantine: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "postal_code": self.postal_code,
            "authoritative_path_ids": list(self.authoritative_path_ids),
            "reason": self.reason,
            "quarantine": self.quarantine,
        }


def _resolve_paths_for_request(
    record: JurisdictionSourceRecord,
    path_ids: Sequence[str],
) -> list[AcquisitionPath]:
    by_id = {path.path_id: path for path in record.acquisition_paths}
    resolved: list[AcquisitionPath] = []
    for path_id in path_ids:
        key = _require_non_empty_str(path_id, "acquisition_path_id", maximum=128)
        if key not in by_id:
            raise MissingAuthoritativePathError(
                f"unknown acquisition_path_id {key!r} for {record.postal_code}"
            )
        resolved.append(by_id[key])
    return resolved


def evaluate_admission(
    request: AdmissionRequest,
    *,
    catalog: Optional[OfficialSourceCatalog] = None,
) -> AdmissionDecision:
    """Evaluate whether an acquisition may enter the admitted corpus.

    Fail-closed rules:

    * postal code must be in the exact 51-set and present in the catalog;
    * at least one selected path must be authoritative;
    * secondary-only selections are rejected (or quarantined if explicitly
      requested via ``allow_secondary_quarantine``);
    * mutable release/edition/as-of pins are rejected;
    * optional source URL must respect the selected paths' domain constraints.
    """

    cat = catalog if catalog is not None else get_official_source_catalog()
    postal = normalize_postal_code(request.postal_code)
    record = cat.get(postal)

    for field_name, raw in (
        ("release_point", request.release_point),
        ("edition", request.edition),
        ("as_of", request.as_of),
    ):
        if raw is not None and str(raw).strip() != "":
            reject_mutable_reference(raw, field_name=field_name)

    if not request.acquisition_path_ids:
        raise MissingAuthoritativePathError(
            f"admission for {postal} requires at least one acquisition_path_id"
        )
    selected = _resolve_paths_for_request(record, request.acquisition_path_ids)
    authoritative = [path for path in selected if path.is_authoritative()]
    secondary_only = not authoritative and all(
        path.authority_class is AuthorityClass.SECONDARY or path.role is SourceRole.SECONDARY
        for path in selected
    )

    if request.source_url:
        url = _require_http_url(request.source_url, "source_url")
        host = _host_of(url)
        if is_secondary_host(host) and not secondary_only:
            # Secondary host used while claiming an official path → reject.
            if any(path.is_authoritative() for path in selected):
                raise DomainConstraintError(
                    f"source_url host {host!r} is secondary and cannot satisfy "
                    f"authoritative admission for {postal}"
                )
        allowed_hosts: set[str] = set()
        for path in selected:
            allowed_hosts.update(path.allowed_domains)
        if allowed_hosts and not any(
            host == domain or host.endswith("." + domain) for domain in allowed_hosts
        ):
            raise DomainConstraintError(
                f"source_url host {host!r} is outside allowed domains "
                f"{sorted(allowed_hosts)!r} for {postal}"
            )

    if request.authority_class is AuthorityClass.SECONDARY or secondary_only:
        if request.allow_secondary_quarantine:
            return AdmissionDecision(
                admitted=False,
                postal_code=postal,
                authoritative_path_ids=(),
                reason="secondary-only material quarantined; not admitted to corpus",
                quarantine=True,
            )
        raise SecondaryOnlyAdmissionError(
            f"admission for {postal} rejects secondary-only sources; "
            "catalog an authoritative legislature/reviser/code-publisher/DC Council "
            "path or an approved exception"
        )

    if not authoritative:
        raise MissingAuthoritativePathError(
            f"admission for {postal} requires at least one authoritative acquisition path"
        )

    return AdmissionDecision(
        admitted=True,
        postal_code=postal,
        authoritative_path_ids=tuple(path.path_id for path in authoritative),
        reason="authoritative acquisition path present; mutable pins absent",
        quarantine=False,
    )


def require_authoritative_admission(
    postal_code: Any,
    acquisition_path_ids: Sequence[str],
    *,
    release_point: Optional[str] = None,
    edition: Optional[str] = None,
    as_of: Optional[str] = None,
    source_url: Optional[str] = None,
    catalog: Optional[OfficialSourceCatalog] = None,
) -> AdmissionDecision:
    """Admit only when an authoritative, non-mutable path is selected."""

    decision = evaluate_admission(
        AdmissionRequest(
            postal_code=str(postal_code),
            acquisition_path_ids=tuple(acquisition_path_ids),
            release_point=release_point,
            edition=edition,
            as_of=as_of,
            source_url=source_url,
        ),
        catalog=catalog,
    )
    if not decision.admitted:
        raise SecondaryOnlyAdmissionError(decision.reason)
    return decision


def catalog_authoritative_coverage(
    catalog: Optional[OfficialSourceCatalog] = None,
) -> Mapping[str, tuple[str, ...]]:
    """Return postal_code → authoritative path_id tuple for every jurisdiction."""

    cat = catalog if catalog is not None else get_official_source_catalog()
    return MappingProxyType(
        {
            record.postal_code: tuple(path.path_id for path in record.authoritative_paths())
            for record in cat.jurisdictions
        }
    )


def assert_catalog_invariants(catalog: Optional[OfficialSourceCatalog] = None) -> None:
    """Assert sealed catalog invariants used by unit tests and preflight."""

    cat = catalog if catalog is not None else get_official_source_catalog()
    if cat.jurisdiction_count != EXPECTED_JURISDICTION_COUNT:
        raise CatalogSchemaError("jurisdiction_count mismatch")
    codes = validate_jurisdiction_set(cat.postal_codes())
    if "DC" not in codes:
        raise CatalogSchemaError("catalog must include DC")
    coverage = catalog_authoritative_coverage(cat)
    for code in codes:
        paths = coverage.get(code) or ()
        if not paths:
            raise MissingAuthoritativePathError(
                f"{code} lacks an authoritative acquisition path"
            )


__all__ = [
    "SCHEMA_VERSION",
    "CATALOG_SCHEMA_VERSION",
    "TASK_ID",
    "EXPECTED_JURISDICTION_COUNT",
    "CANONICAL_JURISDICTIONS",
    "CANONICAL_JURISDICTION_NAMES",
    "DEFAULT_CATALOG_RELATIVE_PATH",
    "CURRENTNESS_DISCLAIMER",
    "SECONDARY_HOST_MARKERS",
    "AUTHORITATIVE_ROLES",
    "AUTHORITATIVE_AUTHORITY_CLASSES",
    "StateLawsSourcePolicyError",
    "JurisdictionSetError",
    "CatalogSchemaError",
    "MissingAuthoritativePathError",
    "SecondaryOnlyAdmissionError",
    "MutableReferenceError",
    "DomainConstraintError",
    "AuthorityExceptionError",
    "SourceRole",
    "AuthorityClass",
    "DiscoveryMode",
    "DelegatedInventoryPath",
    "AcquisitionPath",
    "CodeFamily",
    "JurisdictionSourceRecord",
    "OfficialSourceCatalog",
    "AdmissionRequest",
    "AdmissionDecision",
    "is_secondary_host",
    "is_mutable_reference",
    "reject_mutable_reference",
    "normalize_postal_code",
    "validate_jurisdiction_set",
    "repository_root",
    "default_catalog_path",
    "load_official_source_catalog",
    "get_official_source_catalog",
    "clear_catalog_cache",
    "evaluate_admission",
    "require_authoritative_admission",
    "catalog_authoritative_coverage",
    "assert_catalog_invariants",
]
