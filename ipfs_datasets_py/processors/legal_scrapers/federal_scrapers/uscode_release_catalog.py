"""Exact all-title U.S. Code release catalog (USCIR-005).

Resolves one approved exact release point, enumerates every expected title
package in the sealed baseline span (Titles 1–52 and 54), acquires packages
deterministically from sealed fixtures, checkpoints resume receipts, and
reports missing/excluded packages.

Design invariants
-----------------
* Fixture acquisition is deterministic (no live network I/O by default).
* Title completeness is explicit: every required title is accepted, excluded,
  or reported missing — never silently omitted.
* Resume does not redownload verified packages whose checkpoint receipt and
  on-disk checksum still match.
* Every accepted package binds a content checksum and the approved release
  point (or an explicitly approved mixed-vintage override).
* Proposed-latest discovery cannot mint final provenance; admission requires
  an approved exact release (USCIR-004).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    CANONICAL_USCODE_TITLES,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_ACQUIRED_AT,
    DEFAULT_APPROVED_AT,
    DEFAULT_APPROVED_CONGRESS,
    DEFAULT_APPROVED_RELEASE,
    DEFAULT_APPROVED_RELEASE_POINT,
    DEFAULT_DISCOVERED_AT,
    DEFAULT_PROVIDER_OLRC,
    EXPECTED_TITLE_COUNT,
    USHOUSE_DOWNLOAD_PAGE,
    AllTitleReleaseManifest,
    ApprovedReleasePoint,
    ExclusionKind,
    HardCodedLatestEditionError,
    MissingApprovedReleaseError,
    ProposedReleasePoint,
    ReleasePointRole,
    ResumeReceiptError,
    SourceProvider,
    TitleExclusion,
    TitlePackageProvenance,
    TitlePackageStatus,
    TitleResumeReceipt,
    UnapprovedMixedVintageError,
    UnapprovedProposedReleaseError,
    UscodeSourcePolicy,
    UscodeSourcePolicyError,
    VerificationResult,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    expected_title_package_sha256,
    normalize_title,
    parse_release_point_id,
    require_approved_exact,
    require_canonical_title,
    titles_missing_from_manifest,
    ushouse_releasepoint_zip_url,
    ushouse_title_code,
)

SCHEMA_VERSION = "uscode-release-catalog-v1"
FIXTURE_SCHEMA_VERSION = "uscode-release-catalog-fixture-v1"

# Fixture identity defaults (aligned with USCIR-004 sealed release).
DEFAULT_FIXTURE_ID = "uscode-catalog-us-pl-118-45"
DEFAULT_CATALOG_APPROVED_BY = "uscir-005-fixture-seal"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeReleaseCatalogError(ValueError):
    """Base error for all-title release catalog failures."""


class CatalogFixtureSchemaError(UscodeReleaseCatalogError):
    """Raised when the sealed catalog fixture recipe is malformed."""


class CatalogCompletenessError(UscodeReleaseCatalogError):
    """Raised when title completeness fails closed and enforcement is requested."""


class CatalogCheckpointError(UscodeReleaseCatalogError):
    """Raised when a catalog checkpoint is malformed or non-atomic write fails."""


class CatalogAcquisitionError(UscodeReleaseCatalogError):
    """Raised when package acquisition cannot bind checksum and release point."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PackageDisposition(str, Enum):
    """Per-title disposition after catalog acquisition or resume."""

    ACCEPTED = "accepted"
    EXCLUDED = "excluded"
    MISSING = "missing"
    SKIPPED_VERIFIED = "skipped_verified"
    REDOWNLOAD = "redownload"
    VERIFY_FAILED = "verify_failed"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "PackageDisposition":
        if isinstance(value, PackageDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise UscodeReleaseCatalogError(f"unknown package disposition: {value!r}")


class CatalogAcquisitionMode(str, Enum):
    """How packages were obtained."""

    FIXTURE = "fixture"
    RESUME = "resume"
    POLICY = "policy"

    @classmethod
    def coerce(cls, value: Any) -> "CatalogAcquisitionMode":
        if isinstance(value, CatalogAcquisitionMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise UscodeReleaseCatalogError(f"unknown acquisition mode: {value!r}")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitlePackageSpec:
    """Expected package descriptor for one title under the approved release."""

    title: str
    release_point: str
    package_id: str
    source_url: str
    expected_sha256: str
    provider: SourceProvider = SourceProvider.OLRC_HOUSE
    format_kind: str = "xml"
    required: bool = True
    exclusion: Optional[TitleExclusion] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", require_canonical_title(self.title))
        rp = str(self.release_point)
        if not rp.upper().startswith("USCODE-"):
            rp, _, _ = parse_release_point_id(rp)
        object.__setattr__(self, "release_point", rp)
        object.__setattr__(self, "package_id", str(self.package_id).strip())
        if not self.package_id:
            raise UscodeReleaseCatalogError("package_id must be non-empty")
        object.__setattr__(self, "source_url", str(self.source_url).strip())
        if not self.source_url:
            raise UscodeReleaseCatalogError("source_url must be non-empty")
        sha = str(self.expected_sha256).strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise UscodeReleaseCatalogError(
                f"expected_sha256 must be a lowercase 64-char hex SHA-256, got {self.expected_sha256!r}"
            )
        object.__setattr__(self, "expected_sha256", sha)
        object.__setattr__(
            self, "provider", SourceProvider.coerce(self.provider).canonical()
        )
        object.__setattr__(
            self, "format_kind", str(self.format_kind or "xml").strip().lower()
        )
        if self.exclusion is not None and not isinstance(self.exclusion, TitleExclusion):
            if isinstance(self.exclusion, Mapping):
                object.__setattr__(self, "exclusion", TitleExclusion.from_dict(self.exclusion))
            else:
                raise UscodeReleaseCatalogError("exclusion must be a TitleExclusion or mapping")
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseCatalogError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "exclusion": None if self.exclusion is None else self.exclusion.to_dict(),
            "expected_sha256": self.expected_sha256,
            "format_kind": self.format_kind,
            "metadata": dict(sorted(self.metadata.items(), key=lambda kv: str(kv[0]))),
            "package_id": self.package_id,
            "provider": self.provider.value,
            "release_point": self.release_point,
            "required": bool(self.required),
            "source_url": self.source_url,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitlePackageSpec":
        if not isinstance(value, Mapping):
            raise UscodeReleaseCatalogError("title package spec must be a mapping")
        return cls(
            title=str(value.get("title")),
            release_point=str(value.get("release_point")),
            package_id=str(value.get("package_id") or value.get("release_point")),
            source_url=str(value.get("source_url")),
            expected_sha256=str(
                value.get("expected_sha256")
                or value.get("content_sha256")
                or value.get("artifact_sha256")
            ),
            provider=SourceProvider.coerce(value.get("provider") or DEFAULT_PROVIDER_OLRC),
            format_kind=str(value.get("format_kind") or value.get("format") or "xml"),
            required=bool(value.get("required", True)),
            exclusion=value.get("exclusion"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class TitlePackageAcquisition:
    """Result of acquiring (or skipping) one title package.

    Accepted packages always bind ``content_sha256`` and ``release_point``.
    """

    title: str
    disposition: PackageDisposition
    release_point: Optional[str]
    content_sha256: Optional[str]
    package_id: Optional[str] = None
    source_url: Optional[str] = None
    status: TitlePackageStatus = TitlePackageStatus.PENDING
    verification: VerificationResult = VerificationResult.UNVERIFIED
    provenance: Optional[TitlePackageProvenance] = None
    resume_receipt: Optional[TitleResumeReceipt] = None
    exclusion: Optional[TitleExclusion] = None
    redownloaded: bool = False
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", require_canonical_title(self.title))
        object.__setattr__(self, "disposition", PackageDisposition.coerce(self.disposition))
        object.__setattr__(self, "status", TitlePackageStatus.coerce(self.status))
        object.__setattr__(
            self, "verification", VerificationResult.coerce(self.verification)
        )
        if self.release_point is not None:
            rp = str(self.release_point)
            if not rp.upper().startswith("USCODE-"):
                rp, _, _ = parse_release_point_id(rp)
            object.__setattr__(self, "release_point", rp)
        if self.content_sha256 is not None:
            sha = str(self.content_sha256).strip().lower()
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise CatalogAcquisitionError(
                    f"content_sha256 must be a lowercase 64-char hex SHA-256 for title {self.title}"
                )
            object.__setattr__(self, "content_sha256", sha)
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseCatalogError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        # Accepted packages must bind checksum + release point.
        if self.disposition is PackageDisposition.ACCEPTED:
            if not self.release_point:
                raise CatalogAcquisitionError(
                    f"accepted package for title {self.title} must bind release_point"
                )
            if not self.content_sha256:
                raise CatalogAcquisitionError(
                    f"accepted package for title {self.title} must bind content_sha256"
                )
            if self.verification is not VerificationResult.VERIFIED:
                raise CatalogAcquisitionError(
                    f"accepted package for title {self.title} requires verification=verified"
                )

        if self.disposition is PackageDisposition.EXCLUDED and self.exclusion is None:
            raise CatalogAcquisitionError(
                f"excluded package for title {self.title} requires an exclusion record"
            )

    @property
    def is_accepted(self) -> bool:
        return self.disposition is PackageDisposition.ACCEPTED

    @property
    def is_complete_slot(self) -> bool:
        """True when this title is accounted for (accepted, excluded, or skipped)."""

        return self.disposition in {
            PackageDisposition.ACCEPTED,
            PackageDisposition.EXCLUDED,
            PackageDisposition.SKIPPED_VERIFIED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "exclusion": None if self.exclusion is None else self.exclusion.to_dict(),
            "metadata": dict(sorted(self.metadata.items(), key=lambda kv: str(kv[0]))),
            "notes": self.notes,
            "package_id": self.package_id,
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "redownloaded": bool(self.redownloaded),
            "release_point": self.release_point,
            "resume_receipt": (
                None if self.resume_receipt is None else self.resume_receipt.to_dict()
            ),
            "source_url": self.source_url,
            "status": self.status.value,
            "title": self.title,
            "verification": self.verification.value,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitlePackageAcquisition":
        if not isinstance(value, Mapping):
            raise UscodeReleaseCatalogError("title package acquisition must be a mapping")
        provenance_raw = value.get("provenance")
        receipt_raw = value.get("resume_receipt")
        exclusion_raw = value.get("exclusion")
        return cls(
            title=str(value.get("title")),
            disposition=PackageDisposition.coerce(value.get("disposition")),
            release_point=value.get("release_point"),
            content_sha256=value.get("content_sha256"),
            package_id=value.get("package_id"),
            source_url=value.get("source_url"),
            status=TitlePackageStatus.coerce(
                value.get("status") or TitlePackageStatus.PENDING
            ),
            verification=VerificationResult.coerce(
                value.get("verification") or VerificationResult.UNVERIFIED
            ),
            provenance=(
                None
                if provenance_raw is None
                else TitlePackageProvenance.from_dict(provenance_raw)
            ),
            resume_receipt=(
                None
                if receipt_raw is None
                else TitleResumeReceipt.from_dict(receipt_raw)
            ),
            exclusion=(
                None
                if exclusion_raw is None
                else TitleExclusion.from_dict(exclusion_raw)
            ),
            redownloaded=bool(value.get("redownloaded", False)),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class TitleCompletenessReport:
    """Explicit title completeness for one catalog acquisition.

    Completeness is complete only when every required title is either accepted
    (or skipped-verified on resume) or explicitly excluded — never when titles
    are silently absent.
    """

    expected_titles: tuple[str, ...]
    expected_count: int
    present_titles: tuple[str, ...]
    accepted_titles: tuple[str, ...]
    excluded_titles: tuple[str, ...]
    missing_titles: tuple[str, ...]
    failed_titles: tuple[str, ...]
    skipped_verified_titles: tuple[str, ...]
    is_complete: bool
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "expected_titles", tuple(str(t) for t in self.expected_titles)
        )
        object.__setattr__(
            self, "present_titles", tuple(str(t) for t in self.present_titles)
        )
        object.__setattr__(
            self, "accepted_titles", tuple(str(t) for t in self.accepted_titles)
        )
        object.__setattr__(
            self, "excluded_titles", tuple(str(t) for t in self.excluded_titles)
        )
        object.__setattr__(
            self, "missing_titles", tuple(str(t) for t in self.missing_titles)
        )
        object.__setattr__(
            self, "failed_titles", tuple(str(t) for t in self.failed_titles)
        )
        object.__setattr__(
            self,
            "skipped_verified_titles",
            tuple(str(t) for t in self.skipped_verified_titles),
        )
        if not isinstance(self.expected_count, int) or self.expected_count < 0:
            raise UscodeReleaseCatalogError("expected_count must be a non-negative int")
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseCatalogError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_titles": list(self.accepted_titles),
            "excluded_titles": list(self.excluded_titles),
            "expected_count": self.expected_count,
            "expected_titles": list(self.expected_titles),
            "failed_titles": list(self.failed_titles),
            "is_complete": bool(self.is_complete),
            "metadata": dict(sorted(self.metadata.items(), key=lambda kv: str(kv[0]))),
            "missing_titles": list(self.missing_titles),
            "notes": self.notes,
            "present_titles": list(self.present_titles),
            "skipped_verified_titles": list(self.skipped_verified_titles),
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TitleCompletenessReport":
        if not isinstance(value, Mapping):
            raise UscodeReleaseCatalogError("completeness report must be a mapping")
        return cls(
            expected_titles=tuple(value.get("expected_titles") or ()),
            expected_count=int(value.get("expected_count") or 0),
            present_titles=tuple(value.get("present_titles") or ()),
            accepted_titles=tuple(value.get("accepted_titles") or ()),
            excluded_titles=tuple(value.get("excluded_titles") or ()),
            missing_titles=tuple(value.get("missing_titles") or ()),
            failed_titles=tuple(value.get("failed_titles") or ()),
            skipped_verified_titles=tuple(value.get("skipped_verified_titles") or ()),
            is_complete=bool(value.get("is_complete")),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CatalogAcquisitionResult:
    """Sealed outcome of an all-title catalog acquisition or resume pass."""

    approved_release: ApprovedReleasePoint
    packages: Mapping[str, TitlePackageAcquisition]
    completeness: TitleCompletenessReport
    mode: CatalogAcquisitionMode
    resume_receipts: Mapping[str, TitleResumeReceipt] = field(default_factory=dict)
    proposed_release: Optional[ProposedReleasePoint] = None
    expected_packages: Mapping[str, TitlePackageSpec] = field(default_factory=dict)
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    schema_version: str = SCHEMA_VERSION
    fixture_id: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    download_count: int = 0
    skip_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.approved_release, ApprovedReleasePoint):
            object.__setattr__(
                self, "approved_release", require_approved_exact(self.approved_release)
            )
        object.__setattr__(self, "mode", CatalogAcquisitionMode.coerce(self.mode))

        package_map: dict[str, TitlePackageAcquisition] = {}
        for key, pkg in (self.packages or {}).items():
            if isinstance(pkg, TitlePackageAcquisition):
                record = pkg
            elif isinstance(pkg, Mapping):
                record = TitlePackageAcquisition.from_dict(pkg)
            else:
                raise UscodeReleaseCatalogError(
                    "packages values must be TitlePackageAcquisition or mapping"
                )
            package_map[record.title] = record
        object.__setattr__(self, "packages", package_map)

        receipt_map: dict[str, TitleResumeReceipt] = {}
        for key, receipt in (self.resume_receipts or {}).items():
            if isinstance(receipt, TitleResumeReceipt):
                record = receipt
            elif isinstance(receipt, Mapping):
                record = TitleResumeReceipt.from_dict(receipt)
            else:
                raise ResumeReceiptError(
                    "resume_receipts values must be TitleResumeReceipt or mapping"
                )
            receipt_map[record.title] = record
        object.__setattr__(self, "resume_receipts", receipt_map)

        spec_map: dict[str, TitlePackageSpec] = {}
        for key, spec in (self.expected_packages or {}).items():
            if isinstance(spec, TitlePackageSpec):
                record = spec
            elif isinstance(spec, Mapping):
                record = TitlePackageSpec.from_dict(spec)
            else:
                raise UscodeReleaseCatalogError(
                    "expected_packages values must be TitlePackageSpec or mapping"
                )
            spec_map[record.title] = record
        object.__setattr__(self, "expected_packages", spec_map)

        if not isinstance(self.completeness, TitleCompletenessReport):
            if isinstance(self.completeness, Mapping):
                object.__setattr__(
                    self, "completeness", TitleCompletenessReport.from_dict(self.completeness)
                )
            else:
                raise UscodeReleaseCatalogError(
                    "completeness must be a TitleCompletenessReport or mapping"
                )

        if self.proposed_release is not None and not isinstance(
            self.proposed_release, ProposedReleasePoint
        ):
            if isinstance(self.proposed_release, Mapping):
                object.__setattr__(
                    self,
                    "proposed_release",
                    ProposedReleasePoint.from_dict(self.proposed_release),
                )
            else:
                raise UscodeReleaseCatalogError(
                    "proposed_release must be a ProposedReleasePoint or mapping"
                )

        object.__setattr__(
            self,
            "currentness_disclaimer",
            str(self.currentness_disclaimer or CURRENTNESS_DISCLAIMER),
        )
        object.__setattr__(self, "schema_version", str(self.schema_version or SCHEMA_VERSION))
        if not isinstance(self.metadata, Mapping):
            raise UscodeReleaseCatalogError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not isinstance(self.download_count, int) or self.download_count < 0:
            raise UscodeReleaseCatalogError("download_count must be a non-negative int")
        if not isinstance(self.skip_count, int) or self.skip_count < 0:
            raise UscodeReleaseCatalogError("skip_count must be a non-negative int")

        # Fail closed: every accepted / skipped-verified package binds checksum + release point.
        for title, pkg in self.packages.items():
            if pkg.disposition in {
                PackageDisposition.ACCEPTED,
                PackageDisposition.SKIPPED_VERIFIED,
            }:
                if not pkg.content_sha256 or not pkg.release_point:
                    raise CatalogAcquisitionError(
                        f"accepted package for title {title} missing checksum or release_point"
                    )

    @property
    def accepted_packages(self) -> Mapping[str, TitlePackageAcquisition]:
        return {
            t: p
            for t, p in self.packages.items()
            if p.disposition
            in {PackageDisposition.ACCEPTED, PackageDisposition.SKIPPED_VERIFIED}
        }

    def result_digest(self) -> str:
        return digest_mapping(self.to_dict())

    def to_manifest(self) -> AllTitleReleaseManifest:
        """Project accepted/excluded packages into an all-title release manifest."""

        titles: dict[str, TitlePackageProvenance] = {}
        receipts: dict[str, TitleResumeReceipt] = {}
        for title, pkg in self.packages.items():
            if pkg.provenance is not None:
                titles[title] = pkg.provenance
            if pkg.resume_receipt is not None:
                receipts[title] = pkg.resume_receipt
            elif title in self.resume_receipts:
                receipts[title] = self.resume_receipts[title]
        return AllTitleReleaseManifest(
            approved_release=self.approved_release,
            titles=titles,
            resume_receipts=receipts,
            proposed_release=self.proposed_release,
            currentness_disclaimer=self.currentness_disclaimer,
            schema_version=self.schema_version
            if self.schema_version.startswith("uscode-source-policy")
            else "uscode-source-policy-v1",
            notes=self.notes,
            metadata={
                "catalog_schema_version": SCHEMA_VERSION,
                "fixture_id": self.fixture_id,
                "mode": self.mode.value,
                **dict(self.metadata),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_release": self.approved_release.to_dict(),
            "completeness": self.completeness.to_dict(),
            "currentness_disclaimer": self.currentness_disclaimer,
            "download_count": self.download_count,
            "expected_packages": {
                k: v.to_dict()
                for k, v in sorted(self.expected_packages.items(), key=lambda kv: kv[0])
            },
            "fixture_id": self.fixture_id,
            "metadata": dict(sorted(self.metadata.items(), key=lambda kv: str(kv[0]))),
            "mode": self.mode.value,
            "notes": self.notes,
            "packages": {
                k: v.to_dict() for k, v in sorted(self.packages.items(), key=lambda kv: kv[0])
            },
            "proposed_release": (
                None if self.proposed_release is None else self.proposed_release.to_dict()
            ),
            "resume_receipts": {
                k: v.to_dict()
                for k, v in sorted(self.resume_receipts.items(), key=lambda kv: kv[0])
            },
            "schema_version": self.schema_version,
            "skip_count": self.skip_count,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "CatalogAcquisitionResult":
        if not isinstance(value, Mapping):
            raise UscodeReleaseCatalogError("catalog acquisition result must be a mapping")
        approved_raw = value.get("approved_release") or value.get("approved")
        if approved_raw is None:
            raise MissingApprovedReleaseError("approved_release is required")
        return cls(
            approved_release=require_approved_exact(approved_raw),
            packages=value.get("packages") or {},
            completeness=value.get("completeness") or {},
            mode=CatalogAcquisitionMode.coerce(
                value.get("mode") or CatalogAcquisitionMode.FIXTURE
            ),
            resume_receipts=value.get("resume_receipts") or {},
            proposed_release=value.get("proposed_release"),
            expected_packages=value.get("expected_packages") or {},
            currentness_disclaimer=str(
                value.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER
            ),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            fixture_id=value.get("fixture_id"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
            download_count=int(value.get("download_count") or 0),
            skip_count=int(value.get("skip_count") or 0),
        )


# ---------------------------------------------------------------------------
# Completeness helpers
# ---------------------------------------------------------------------------


def build_completeness_report(
    packages: Mapping[str, TitlePackageAcquisition] | Iterable[TitlePackageAcquisition],
    *,
    expected_titles: Sequence[str] = CANONICAL_USCODE_TITLES,
    notes: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> TitleCompletenessReport:
    """Build an explicit title completeness report from package dispositions."""

    expected = tuple(require_canonical_title(t) for t in expected_titles)
    expected_set = set(expected)

    if isinstance(packages, Mapping):
        pkg_iter: Iterable[TitlePackageAcquisition] = packages.values()
    else:
        pkg_iter = packages

    by_title: dict[str, TitlePackageAcquisition] = {}
    for pkg in pkg_iter:
        if not isinstance(pkg, TitlePackageAcquisition):
            raise UscodeReleaseCatalogError(
                "packages must be TitlePackageAcquisition records"
            )
        by_title[pkg.title] = pkg

    accepted: list[str] = []
    excluded: list[str] = []
    missing: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    present: list[str] = []

    for title in expected:
        pkg = by_title.get(title)
        if pkg is None:
            missing.append(title)
            continue
        present.append(title)
        if pkg.disposition is PackageDisposition.ACCEPTED:
            accepted.append(title)
        elif pkg.disposition is PackageDisposition.EXCLUDED:
            excluded.append(title)
        elif pkg.disposition is PackageDisposition.SKIPPED_VERIFIED:
            skipped.append(title)
            accepted.append(title)  # accounted as present/verified
        elif pkg.disposition is PackageDisposition.MISSING:
            missing.append(title)
            if title in present:
                # Keep in present if explicitly reported as missing disposition
                # after being listed — treat as not present for completeness.
                present.remove(title)
        elif pkg.disposition in {
            PackageDisposition.FAILED,
            PackageDisposition.VERIFY_FAILED,
            PackageDisposition.REDOWNLOAD,
        }:
            failed.append(title)
        else:
            failed.append(title)

    # Titles outside expected set are ignored for completeness, but recorded.
    extra = sorted(t for t in by_title if t not in expected_set)

    is_complete = (
        len(missing) == 0
        and len(failed) == 0
        and (len(accepted) + len(excluded)) == len(expected)
    )

    return TitleCompletenessReport(
        expected_titles=expected,
        expected_count=len(expected),
        present_titles=tuple(present),
        accepted_titles=tuple(accepted),
        excluded_titles=tuple(excluded),
        missing_titles=tuple(missing),
        failed_titles=tuple(failed),
        skipped_verified_titles=tuple(skipped),
        is_complete=is_complete,
        notes=notes,
        metadata={
            **dict(metadata or {}),
            "extra_titles": extra,
            "accounted_count": len(accepted) + len(excluded),
        },
    )


# ---------------------------------------------------------------------------
# Fixture recipe / IO
# ---------------------------------------------------------------------------


def default_catalog_fixture_path() -> Path:
    """Return the sealed all-title release-catalog fixture path."""

    here = Path(__file__).resolve()
    # processors/legal_scrapers/federal_scrapers/thisfile → repo root is parents[4]
    candidates = [
        here.parents[4] / "tests" / "fixtures" / "legal_ir" / "uscode_release_catalog.json",
        Path.cwd() / "tests" / "fixtures" / "legal_ir" / "uscode_release_catalog.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def build_default_catalog_fixture_payload(
    *,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    congress: str = DEFAULT_APPROVED_CONGRESS,
    release: str = DEFAULT_APPROVED_RELEASE,
    approved_by: str = DEFAULT_CATALOG_APPROVED_BY,
    approved_at: str = DEFAULT_APPROVED_AT,
    discovered_at: str = DEFAULT_DISCOVERED_AT,
    acquired_at: str = DEFAULT_ACQUIRED_AT,
    excluded_titles: Optional[Mapping[str, Mapping[str, Any]]] = None,
    missing_titles: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Build a compact recipe for the sealed all-title catalog fixture.

    Stores generators and shared release identity rather than 53 fully expanded
    package envelopes, keeping the fixture under admission budgets.
    """

    canonical, congress_s, release_s = parse_release_point_id(
        release_point if release_point else f"{congress}/{release}"
    )
    # Recipe-level exclusions (title → exclusion mapping). Default happy-path
    # fixture admits all 53 packages; callers/tests inject exclusions when
    # exercising the excluded disposition path.
    excluded: dict[str, dict[str, Any]] = {}
    for title, excl in (excluded_titles or {}).items():
        title_n = require_canonical_title(title)
        payload = dict(excl)
        payload.setdefault("title", title_n)
        excluded[title_n] = payload

    missing = [require_canonical_title(t) for t in (missing_titles or ())]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "catalog_schema_version": SCHEMA_VERSION,
        "fixture_id": DEFAULT_FIXTURE_ID
        if canonical == DEFAULT_APPROVED_RELEASE_POINT
        else f"uscode-catalog-{canonical.replace('/', '-')}",
        "expected_title_count": EXPECTED_TITLE_COUNT,
        "canonical_titles": list(CANONICAL_USCODE_TITLES),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": (
            "Compact all-title release catalog recipe (USCIR-005). "
            "Resolves one approved exact release, enumerates all expected title "
            "packages, binds checksum + release point per package, and supports "
            "deterministic resume. Expand via expand_catalog_fixture()."
        ),
        "proposed_release": {
            "role": ReleasePointRole.PROPOSED_LATEST.value,
            "release_point": canonical,
            "provider": DEFAULT_PROVIDER_OLRC,
            "congress": congress_s,
            "release": release_s,
            "discovered_at": discovered_at,
            "discovery_source": USHOUSE_DOWNLOAD_PAGE,
            "edition": f"olrc-proposed-{canonical.replace('/', '-')}",
            "notes": (
                "Catalog scrape candidate from the House OLRC download page; "
                "not final provenance."
            ),
        },
        "approved_release": {
            "role": ReleasePointRole.APPROVED_EXACT.value,
            "release_point": canonical,
            "provider": DEFAULT_PROVIDER_OLRC,
            "congress": congress_s,
            "release": release_s,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "edition": f"olrc-{canonical.replace('/', '-')}",
            "notes": "Human-sealed exact release point for all-title catalog admission.",
        },
        "approved_mixed_overrides": {},
        "generators": {
            "title_package": {
                "provider": DEFAULT_PROVIDER_OLRC,
                "format_kind": "xml",
                "status": TitlePackageStatus.VERIFIED.value,
                "verification": VerificationResult.VERIFIED.value,
                "acquired_at": acquired_at,
                "media_type": "application/zip",
                "checksum_seed_template": "{provider}|{release_point}|title-{title}|package",
                "source_url_template": (
                    "https://uscode.house.gov/download/releasepoints/us/pl/"
                    "{congress}/{release}/xml_usc{title_code}@{congress}-{release}.zip"
                ),
            },
            "resume_receipt": {
                "checkpoint_seq_start": 1,
            },
        },
        "excluded_packages": excluded,
        "missing_titles": missing,
        "seed_overrides": {},
        "sample_exclusions": [
            {
                "kind": ExclusionKind.CLASSIFICATION_GAP.value,
                "title": "35",
                "citation": "Pub. L. 117-328 div. W",
                "public_law": "Pub. L. 117-328",
                "reason": (
                    "Classification table records a pending editorial "
                    "reclassification affecting cross-references in Title 35; "
                    "package itself remains admitted."
                ),
            }
        ],
    }


def expand_catalog_fixture(payload: JsonMapping) -> dict[str, Any]:
    """Expand a compact catalog recipe into structured catalog state.

    Returns a mapping with keys:
      ``approved_release``, ``proposed_release``, ``expected_packages``,
      ``packages`` (fixture acquisitions), ``resume_receipts``,
      ``excluded_packages``, ``missing_titles``, ``fixture_id``, etc.
    """

    if not isinstance(payload, Mapping):
        raise CatalogFixtureSchemaError("fixture root must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise CatalogFixtureSchemaError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )

    expected = int(payload.get("expected_title_count") or EXPECTED_TITLE_COUNT)
    titles_list = payload.get("canonical_titles") or list(CANONICAL_USCODE_TITLES)
    if len(titles_list) != expected:
        raise CatalogFixtureSchemaError(
            f"canonical_titles length {len(titles_list)} != expected_title_count {expected}"
        )

    proposed_raw = payload.get("proposed_release")
    proposed = (
        None if proposed_raw is None else ProposedReleasePoint.from_dict(proposed_raw)
    )
    approved = require_approved_exact(
        payload.get("approved_release") or payload.get("approved")
    )

    gen = payload.get("generators") or {}
    pkg_gen = gen.get("title_package") or gen.get("title_provenance") or {}
    receipt_gen = gen.get("resume_receipt") or {}
    seq_start = int(receipt_gen.get("checkpoint_seq_start", 1))

    provider = SourceProvider.coerce(
        pkg_gen.get("provider") or approved.provider
    ).canonical()
    format_kind = str(pkg_gen.get("format_kind") or "xml")
    acquired_at = pkg_gen.get("acquired_at") or DEFAULT_ACQUIRED_AT
    status = TitlePackageStatus.coerce(
        pkg_gen.get("status") or TitlePackageStatus.VERIFIED
    )
    verification = VerificationResult.coerce(
        pkg_gen.get("verification") or VerificationResult.VERIFIED
    )

    seed_overrides = payload.get("seed_overrides") or {}
    excluded_packages_raw = payload.get("excluded_packages") or {}
    missing_titles = {
        require_canonical_title(t) for t in (payload.get("missing_titles") or ())
    }
    inline_packages = payload.get("packages") or {}
    inline_receipts = payload.get("resume_receipts") or {}
    inline_specs = payload.get("expected_packages") or {}

    congress = approved.congress or DEFAULT_APPROVED_CONGRESS
    release = approved.release or DEFAULT_APPROVED_RELEASE

    expected_packages: dict[str, TitlePackageSpec] = {}
    packages: dict[str, TitlePackageAcquisition] = {}
    receipts: dict[str, TitleResumeReceipt] = {}
    excluded_map: dict[str, TitleExclusion] = {}

    for index, title in enumerate(titles_list):
        title_n = require_canonical_title(title)
        override = seed_overrides.get(title_n) or {}
        rp = str(override.get("release_point") or approved.release_point)
        if not rp.upper().startswith("USCODE-"):
            rp, _, _ = parse_release_point_id(rp)

        checksum = str(
            override.get("content_sha256")
            or override.get("expected_sha256")
            or expected_title_package_sha256(
                release_point=rp, title=title_n, provider=provider
            )
        )
        package_id = str(override.get("package_id") or rp)
        source_url = str(
            override.get("source_url")
            or ushouse_releasepoint_zip_url(
                congress=congress,
                release=release,
                title=title_n,
                format_kind=format_kind,
            )
        )

        excl_raw = excluded_packages_raw.get(title_n) or override.get("exclusion")
        exclusion: Optional[TitleExclusion] = None
        if excl_raw is not None:
            if isinstance(excl_raw, TitleExclusion):
                exclusion = excl_raw
            elif isinstance(excl_raw, Mapping):
                excl_payload = dict(excl_raw)
                excl_payload.setdefault("title", title_n)
                exclusion = TitleExclusion.from_dict(excl_payload)
            else:
                raise CatalogFixtureSchemaError(
                    f"excluded_packages[{title_n!r}] must be a mapping"
                )
            excluded_map[title_n] = exclusion

        if title_n in inline_specs:
            spec = TitlePackageSpec.from_dict(inline_specs[title_n])
        else:
            spec = TitlePackageSpec(
                title=title_n,
                release_point=rp,
                package_id=package_id,
                source_url=source_url,
                expected_sha256=checksum,
                provider=provider,
                format_kind=str(override.get("format_kind") or format_kind),
                required=title_n not in missing_titles,
                exclusion=exclusion,
                metadata=override.get("metadata") or {},
            )
        expected_packages[title_n] = spec

        if title_n in missing_titles:
            packages[title_n] = TitlePackageAcquisition(
                title=title_n,
                disposition=PackageDisposition.MISSING,
                release_point=None,
                content_sha256=None,
                package_id=None,
                source_url=source_url,
                status=TitlePackageStatus.FAILED,
                verification=VerificationResult.MISSING,
                notes=f"title {title_n} package missing from catalog fixture",
                metadata={"fixture_missing": True},
            )
            continue

        if title_n in inline_packages:
            pkg = TitlePackageAcquisition.from_dict(inline_packages[title_n])
            packages[title_n] = pkg
            if pkg.resume_receipt is not None:
                receipts[title_n] = pkg.resume_receipt
            continue

        if exclusion is not None:
            prov = TitlePackageProvenance(
                title=title_n,
                release_point=rp,
                provider=provider,
                package_id=package_id,
                source_url=source_url,
                content_sha256=checksum,
                acquired_at=override.get("acquired_at") or acquired_at,
                verification=VerificationResult.MISSING,
                status=TitlePackageStatus.EXCLUDED,
                format_kind=format_kind,
                exclusion=exclusion,
                notes=exclusion.reason,
                metadata=override.get("metadata") or {},
            )
            receipt = TitleResumeReceipt(
                title=title_n,
                release_point=rp,
                package_id=package_id,
                content_sha256=checksum,
                status=TitlePackageStatus.EXCLUDED,
                verification=VerificationResult.MISSING,
                source_url=source_url,
                acquired_at=prov.acquired_at,
                checkpoint_seq=seq_start + index,
                provider=provider,
                notes=exclusion.reason,
                metadata={"schema_version": SCHEMA_VERSION, "format_kind": format_kind},
            )
            packages[title_n] = TitlePackageAcquisition(
                title=title_n,
                disposition=PackageDisposition.EXCLUDED,
                release_point=rp,
                content_sha256=checksum,
                package_id=package_id,
                source_url=source_url,
                status=TitlePackageStatus.EXCLUDED,
                verification=VerificationResult.MISSING,
                provenance=prov,
                resume_receipt=receipt,
                exclusion=exclusion,
                redownloaded=False,
                notes=exclusion.reason,
            )
            receipts[title_n] = receipt
            continue

        # Default admitted package: verified with bound checksum + release point.
        pkg_status = TitlePackageStatus.coerce(override.get("status") or status)
        pkg_verification = VerificationResult.coerce(
            override.get("verification") or verification
        )
        prov = TitlePackageProvenance(
            title=title_n,
            release_point=rp,
            provider=provider,
            package_id=package_id,
            source_url=source_url,
            content_sha256=checksum,
            acquired_at=override.get("acquired_at") or acquired_at,
            verification=pkg_verification,
            status=pkg_status,
            media_type=str(override.get("media_type") or "application/zip"),
            byte_size=override.get("byte_size"),
            format_kind=str(override.get("format_kind") or format_kind),
            notes=override.get("notes"),
            metadata=override.get("metadata") or {},
        )
        if title_n in inline_receipts:
            receipt = TitleResumeReceipt.from_dict(inline_receipts[title_n])
        else:
            receipt = TitleResumeReceipt(
                title=title_n,
                release_point=rp,
                package_id=package_id,
                content_sha256=checksum,
                status=pkg_status,
                verification=pkg_verification,
                source_url=source_url,
                acquired_at=prov.acquired_at,
                checkpoint_seq=seq_start + index,
                provider=provider,
                notes=prov.notes,
                metadata={"schema_version": SCHEMA_VERSION, "format_kind": prov.format_kind},
            )
        packages[title_n] = TitlePackageAcquisition(
            title=title_n,
            disposition=PackageDisposition.ACCEPTED,
            release_point=rp,
            content_sha256=checksum,
            package_id=package_id,
            source_url=source_url,
            status=pkg_status,
            verification=pkg_verification,
            provenance=prov,
            resume_receipt=receipt,
            redownloaded=True,  # first acquisition counts as a download
            notes=prov.notes,
            metadata={"fixture_id": payload.get("fixture_id"), "acquired_from": "fixture"},
        )
        receipts[title_n] = receipt

    return {
        "approved_release": approved,
        "proposed_release": proposed,
        "expected_packages": expected_packages,
        "packages": packages,
        "resume_receipts": receipts,
        "excluded_packages": excluded_map,
        "missing_titles": tuple(sorted(missing_titles)),
        "canonical_titles": tuple(require_canonical_title(t) for t in titles_list),
        "expected_title_count": expected,
        "fixture_id": payload.get("fixture_id"),
        "currentness_disclaimer": str(
            payload.get("currentness_disclaimer") or CURRENTNESS_DISCLAIMER
        ),
        "notes": payload.get("notes"),
        "sample_exclusions": payload.get("sample_exclusions") or [],
        "approved_mixed_overrides": payload.get("approved_mixed_overrides") or {},
        "schema_version": SCHEMA_VERSION,
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "metadata": {
            "fixture_id": payload.get("fixture_id"),
            "sample_exclusions": payload.get("sample_exclusions") or [],
        },
    }


def load_catalog_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    """Load the sealed compact catalog fixture recipe from disk."""

    p = Path(path) if path is not None else default_catalog_fixture_path()
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise CatalogFixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def load_catalog_fixture(path: PathLike | None = None) -> dict[str, Any]:
    """Load and expand the sealed all-title release-catalog fixture."""

    return expand_catalog_fixture(load_catalog_fixture_payload(path))


def write_default_catalog_fixture(path: PathLike | None = None) -> Path:
    """Materialize the compact default catalog fixture recipe."""

    p = Path(path) if path is not None else default_catalog_fixture_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_catalog_fixture_payload()
    p.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically (temp file + os.replace)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def default_checkpoint_directory() -> Path:
    """Return the preferred catalog checkpoint directory.

    Prefers ``$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR`` when set, otherwise
    a local ``.uscode_release_catalog_checkpoints`` directory under cwd.
    """

    env = os.environ.get("IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR")
    if env:
        return Path(env)
    return Path.cwd() / ".uscode_release_catalog_checkpoints"


# ---------------------------------------------------------------------------
# Catalog engine
# ---------------------------------------------------------------------------


class UscodeReleaseCatalog:
    """Exact all-title release catalog for the sealed US Code baseline.

    Resolves one approved release, enumerates expected title packages,
    acquires packages from sealed fixtures (network opt-in is out of scope
    for unit tests), checkpoints resume receipts, and reports missing or
    excluded packages.
    """

    def __init__(
        self,
        *,
        policy: Optional[UscodeSourcePolicy] = None,
        fixture_path: PathLike | None = None,
        checkpoint_dir: PathLike | None = None,
        required_titles: Sequence[str] = CANONICAL_USCODE_TITLES,
        allow_network: bool = False,
    ) -> None:
        self._policy = policy if policy is not None else UscodeSourcePolicy(
            required_titles=required_titles
        )
        self.fixture_path = (
            Path(fixture_path) if fixture_path is not None else default_catalog_fixture_path()
        )
        self.checkpoint_dir = (
            Path(checkpoint_dir)
            if checkpoint_dir is not None
            else default_checkpoint_directory()
        )
        self._required_titles: tuple[str, ...] = tuple(
            require_canonical_title(t) for t in required_titles
        )
        self.allow_network = bool(allow_network)
        self._last_result: Optional[CatalogAcquisitionResult] = None
        self._expected_packages: dict[str, TitlePackageSpec] = {}
        self._packages: dict[str, TitlePackageAcquisition] = {}
        self._receipts: dict[str, TitleResumeReceipt] = {}
        self._fixture_state: Optional[dict[str, Any]] = None

    # -- properties --------------------------------------------------------

    @property
    def policy(self) -> UscodeSourcePolicy:
        return self._policy

    @property
    def required_titles(self) -> tuple[str, ...]:
        return self._required_titles

    @property
    def last_result(self) -> Optional[CatalogAcquisitionResult]:
        return self._last_result

    @property
    def expected_packages(self) -> Mapping[str, TitlePackageSpec]:
        return dict(self._expected_packages)

    @property
    def packages(self) -> Mapping[str, TitlePackageAcquisition]:
        return dict(self._packages)

    @property
    def resume_receipts(self) -> Mapping[str, TitleResumeReceipt]:
        return dict(self._receipts)

    # -- release resolution ------------------------------------------------

    def resolve_approved_release(
        self,
        *,
        release_point: Any | None = None,
        approved_by: str = DEFAULT_CATALOG_APPROVED_BY,
        approved_at: Any = DEFAULT_APPROVED_AT,
        provider: SourceProvider | str = SourceProvider.OLRC_HOUSE,
        edition: Optional[str] = None,
        notes: Optional[str] = None,
        from_fixture: bool = False,
    ) -> ApprovedReleasePoint:
        """Resolve and seal one approved exact release point for the catalog.

        When *from_fixture* is True, the approved release is taken from the
        sealed catalog fixture. Proposed-latest discovery alone is never
        admitted as final provenance.
        """

        if from_fixture:
            state = self._ensure_fixture_state()
            approved = state["approved_release"]
            proposed = state.get("proposed_release")
            if proposed is not None:
                self._policy.propose_latest_from_discovery(
                    release_point=proposed.release_point,
                    provider=proposed.provider,
                    discovered_at=proposed.discovered_at,
                    discovery_source=proposed.discovery_source,
                    edition=proposed.edition,
                    notes=proposed.notes,
                )
            self._policy.approve_exact_release(
                approved,
                approved_by=approved.approved_by,
                approved_at=approved.approved_at,
                edition=approved.edition,
                notes=approved.notes,
            )
            for title, alt in (state.get("approved_mixed_overrides") or {}).items():
                self._policy.approve_mixed_override(title, alt)
            return self._policy.require_approved()

        if release_point is None:
            if self._policy.approved_release is not None:
                return self._policy.require_approved()
            raise MissingApprovedReleaseError(
                "no approved exact release point; supply release_point or from_fixture=True"
            )

        # Reject hard-coded latest before approval.
        if isinstance(release_point, str):
            try:
                parse_release_point_id(release_point)
            except HardCodedLatestEditionError:
                raise
            except UscodeSourcePolicyError:
                # Allow govinfo-style package ids through approve_exact_release.
                pass

        if isinstance(release_point, ProposedReleasePoint):
            self._policy._proposed = release_point  # record discovery
            return self._policy.approve_exact_release(
                release_point,
                approved_by=approved_by,
                approved_at=approved_at,
                provider=provider,
                edition=edition,
                notes=notes,
            )

        return self._policy.approve_exact_release(
            release_point,
            approved_by=approved_by,
            approved_at=approved_at,
            provider=provider,
            edition=edition,
            notes=notes,
        )

    def propose_latest_from_discovery(
        self,
        *,
        release_point: Any,
        provider: SourceProvider | str = SourceProvider.OLRC_HOUSE,
        discovered_at: Any = DEFAULT_DISCOVERED_AT,
        discovery_source: str = USHOUSE_DOWNLOAD_PAGE,
        edition: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ProposedReleasePoint:
        """Record a discovery-only proposed release (not final provenance)."""

        return self._policy.propose_latest_from_discovery(
            release_point=release_point,
            provider=provider,
            discovered_at=discovered_at,
            discovery_source=discovery_source,
            edition=edition,
            notes=notes,
        )

    # -- package enumeration -----------------------------------------------

    def enumerate_expected_packages(
        self,
        *,
        format_kind: str = "xml",
        from_fixture: bool = False,
    ) -> dict[str, TitlePackageSpec]:
        """Enumerate every expected title package under the approved release."""

        if from_fixture:
            state = self._ensure_fixture_state()
            self._expected_packages = dict(state["expected_packages"])
            return dict(self._expected_packages)

        approved = self._policy.require_approved()
        specs: dict[str, TitlePackageSpec] = {}
        for title in self._required_titles:
            rp = self._policy.expected_release_for_title(title)
            if not str(rp).upper().startswith("USCODE-"):
                rp_n, congress, release = parse_release_point_id(rp)
            else:
                rp_n = rp
                congress = approved.congress or DEFAULT_APPROVED_CONGRESS
                release = approved.release or DEFAULT_APPROVED_RELEASE
            provider = approved.provider
            checksum = expected_title_package_sha256(
                release_point=rp_n, title=title, provider=provider
            )
            source_url = ushouse_releasepoint_zip_url(
                congress=congress or approved.congress or DEFAULT_APPROVED_CONGRESS,
                release=release or approved.release or DEFAULT_APPROVED_RELEASE,
                title=title,
                format_kind=format_kind,
            )
            specs[title] = TitlePackageSpec(
                title=title,
                release_point=rp_n,
                package_id=rp_n,
                source_url=source_url,
                expected_sha256=checksum,
                provider=provider,
                format_kind=format_kind,
                required=True,
            )
        self._expected_packages = specs
        return dict(specs)

    # -- fixture acquisition -----------------------------------------------

    def _ensure_fixture_state(self) -> dict[str, Any]:
        if self._fixture_state is None:
            self._fixture_state = load_catalog_fixture(self.fixture_path)
        return self._fixture_state

    def load_fixture(self, path: PathLike | None = None) -> dict[str, Any]:
        """Load and expand a catalog fixture, updating fixture_path when given."""

        if path is not None:
            self.fixture_path = Path(path)
            self._fixture_state = None
        state = self._ensure_fixture_state()
        return state

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        checkpoint: bool = True,
        require_complete: bool = False,
    ) -> CatalogAcquisitionResult:
        """Acquire all title packages deterministically from a sealed fixture.

        Every accepted package binds ``content_sha256`` and ``release_point``.
        Title completeness is reported explicitly (missing/excluded listed).
        """

        if path is not None:
            self.fixture_path = Path(path)
            self._fixture_state = None

        state = self._ensure_fixture_state()
        approved = self.resolve_approved_release(from_fixture=True)
        expected = self.enumerate_expected_packages(from_fixture=True)

        packages: dict[str, TitlePackageAcquisition] = {}
        receipts: dict[str, TitleResumeReceipt] = {}
        download_count = 0

        for title in self._required_titles:
            pkg = state["packages"].get(title)
            if pkg is None:
                packages[title] = TitlePackageAcquisition(
                    title=title,
                    disposition=PackageDisposition.MISSING,
                    release_point=None,
                    content_sha256=None,
                    status=TitlePackageStatus.FAILED,
                    verification=VerificationResult.MISSING,
                    notes=f"title {title} absent from fixture expansion",
                )
                continue

            # Re-validate accepted packages bind checksum + release point.
            if pkg.disposition is PackageDisposition.ACCEPTED:
                if not pkg.content_sha256 or not pkg.release_point:
                    raise CatalogAcquisitionError(
                        f"fixture package for title {title} missing checksum or release_point"
                    )
                # Admit into policy for mixed-vintage checks.
                if pkg.provenance is not None:
                    self._policy.record_title_provenance(
                        pkg.provenance, build_receipt=False
                    )
                download_count += 1 if pkg.redownloaded else 0
            elif pkg.disposition is PackageDisposition.EXCLUDED:
                if pkg.provenance is not None:
                    self._policy.record_title_provenance(
                        pkg.provenance, build_receipt=False
                    )

            packages[title] = pkg
            if pkg.resume_receipt is not None:
                receipts[title] = pkg.resume_receipt
                self._receipts[title] = pkg.resume_receipt
            self._packages[title] = pkg

        # Ensure every expected title has an entry (explicit completeness).
        for title in self._required_titles:
            if title not in packages:
                packages[title] = TitlePackageAcquisition(
                    title=title,
                    disposition=PackageDisposition.MISSING,
                    release_point=None,
                    content_sha256=None,
                    status=TitlePackageStatus.FAILED,
                    verification=VerificationResult.MISSING,
                    notes=f"title {title} not enumerated in acquisition",
                )

        completeness = build_completeness_report(
            packages,
            expected_titles=self._required_titles,
            notes="Fixture acquisition completeness",
            metadata={"mode": CatalogAcquisitionMode.FIXTURE.value},
        )
        if require_complete and not completeness.is_complete:
            raise CatalogCompletenessError(
                "catalog acquisition incomplete: "
                f"missing={list(completeness.missing_titles)} "
                f"failed={list(completeness.failed_titles)}"
            )

        result = CatalogAcquisitionResult(
            approved_release=approved,
            packages=packages,
            completeness=completeness,
            mode=CatalogAcquisitionMode.FIXTURE,
            resume_receipts=receipts,
            proposed_release=state.get("proposed_release"),
            expected_packages=expected,
            currentness_disclaimer=state.get(
                "currentness_disclaimer", CURRENTNESS_DISCLAIMER
            ),
            schema_version=SCHEMA_VERSION,
            fixture_id=state.get("fixture_id"),
            notes=state.get("notes"),
            metadata={
                "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
                "sample_exclusions": state.get("sample_exclusions") or [],
            },
            download_count=download_count,
            skip_count=0,
        )
        self._last_result = result

        if checkpoint:
            self.checkpoint_receipts(result)

        return result

    def acquire_title_from_fixture(
        self,
        title: Any,
        *,
        path: PathLike | None = None,
    ) -> TitlePackageAcquisition:
        """Acquire a single title package from the sealed fixture."""

        title_n = require_canonical_title(title)
        if path is not None or self._fixture_state is None:
            self.load_fixture(path)
        state = self._ensure_fixture_state()
        if self._policy.approved_release is None:
            self.resolve_approved_release(from_fixture=True)
        pkg = state["packages"].get(title_n)
        if pkg is None:
            acq = TitlePackageAcquisition(
                title=title_n,
                disposition=PackageDisposition.MISSING,
                release_point=None,
                content_sha256=None,
                status=TitlePackageStatus.FAILED,
                verification=VerificationResult.MISSING,
                notes=f"title {title_n} absent from fixture",
            )
        else:
            acq = pkg
            if acq.provenance is not None and acq.disposition in {
                PackageDisposition.ACCEPTED,
                PackageDisposition.EXCLUDED,
            }:
                self._policy.record_title_provenance(acq.provenance, build_receipt=False)
            if acq.resume_receipt is not None:
                self._receipts[title_n] = acq.resume_receipt
        self._packages[title_n] = acq
        return acq

    # -- resume ------------------------------------------------------------

    def resume(
        self,
        *,
        prior: CatalogAcquisitionResult | Mapping[str, Any] | None = None,
        checkpoint_path: PathLike | None = None,
        on_disk_checksums: Optional[Mapping[str, str]] = None,
        redownload_missing: bool = True,
        require_complete: bool = False,
    ) -> CatalogAcquisitionResult:
        """Resume catalog acquisition without redownloading verified packages.

        For each title with a verified resume receipt whose on-disk checksum
        still matches (or is trusted when no on-disk hash is supplied), the
        package is marked ``skipped_verified`` and is **not** redownloaded.
        """

        if prior is None and checkpoint_path is None:
            # Fall back to last in-memory result or default checkpoint file.
            if self._last_result is not None:
                prior = self._last_result
            else:
                checkpoint_path = self.checkpoint_dir / "catalog_checkpoint.json"

        if prior is None:
            prior = self.load_checkpoint(checkpoint_path)

        if isinstance(prior, Mapping):
            # Accept either a full result or a checkpoint envelope.
            if "packages" in prior and "approved_release" in prior:
                prior_result = CatalogAcquisitionResult.from_dict(prior)
            elif "result" in prior:
                prior_result = CatalogAcquisitionResult.from_dict(prior["result"])
            else:
                raise CatalogCheckpointError(
                    "checkpoint payload must contain packages/approved_release or result"
                )
        else:
            prior_result = prior

        approved = prior_result.approved_release
        self._policy.approve_exact_release(
            approved,
            approved_by=approved.approved_by,
            approved_at=approved.approved_at,
            edition=approved.edition,
            notes=approved.notes,
        )
        if prior_result.proposed_release is not None:
            self._policy._proposed = prior_result.proposed_release

        disk = {
            require_canonical_title(t): str(h).lower()
            for t, h in (on_disk_checksums or {}).items()
        }
        packages: dict[str, TitlePackageAcquisition] = {}
        receipts: dict[str, TitleResumeReceipt] = {}
        download_count = 0
        skip_count = 0

        # Ensure fixture state is available for redownload of non-verified titles.
        fixture_packages: Mapping[str, TitlePackageAcquisition] = {}
        if redownload_missing:
            try:
                fixture_packages = self._ensure_fixture_state()["packages"]
            except (OSError, CatalogFixtureSchemaError, FileNotFoundError):
                fixture_packages = {}

        for title in self._required_titles:
            prior_pkg = prior_result.packages.get(title)
            prior_receipt = prior_result.resume_receipts.get(title)
            if prior_receipt is None and prior_pkg is not None:
                prior_receipt = prior_pkg.resume_receipt

            if prior_receipt is not None and prior_receipt.is_verified:
                on_disk = disk.get(title)
                disposition_map = self._policy.resume_from_receipt(
                    prior_receipt, on_disk_sha256=on_disk
                )
                if disposition_map["should_skip_redownload"]:
                    # Reconstruct skipped acquisition from prior without redownload.
                    base = prior_pkg
                    packages[title] = TitlePackageAcquisition(
                        title=title,
                        disposition=PackageDisposition.SKIPPED_VERIFIED,
                        release_point=prior_receipt.release_point,
                        content_sha256=prior_receipt.content_sha256,
                        package_id=prior_receipt.package_id,
                        source_url=prior_receipt.source_url,
                        status=TitlePackageStatus.VERIFIED,
                        verification=VerificationResult.VERIFIED,
                        provenance=None if base is None else base.provenance,
                        resume_receipt=prior_receipt,
                        redownloaded=False,
                        notes="resume: verified package skipped (no redownload)",
                        metadata={
                            "resume_action": "skip",
                            "receipt_digest": prior_receipt.receipt_digest,
                        },
                    )
                    receipts[title] = prior_receipt
                    skip_count += 1
                    self._packages[title] = packages[title]
                    self._receipts[title] = prior_receipt
                    continue
                # verify_failed or redownload: fall through to fixture re-acquire.

            # Not verified / needs redownload — re-acquire from fixture if available.
            if redownload_missing and title in fixture_packages:
                fresh = fixture_packages[title]
                if fresh.disposition is PackageDisposition.ACCEPTED:
                    # Count as a redownload.
                    packages[title] = TitlePackageAcquisition(
                        title=title,
                        disposition=PackageDisposition.ACCEPTED,
                        release_point=fresh.release_point,
                        content_sha256=fresh.content_sha256,
                        package_id=fresh.package_id,
                        source_url=fresh.source_url,
                        status=fresh.status,
                        verification=fresh.verification,
                        provenance=fresh.provenance,
                        resume_receipt=fresh.resume_receipt,
                        exclusion=fresh.exclusion,
                        redownloaded=True,
                        notes="resume: redownloaded from fixture",
                        metadata={"resume_action": "redownload"},
                    )
                    download_count += 1
                    if fresh.resume_receipt is not None:
                        receipts[title] = fresh.resume_receipt
                        self._receipts[title] = fresh.resume_receipt
                else:
                    packages[title] = fresh
                    if fresh.resume_receipt is not None:
                        receipts[title] = fresh.resume_receipt
                self._packages[title] = packages[title]
                continue

            if prior_pkg is not None:
                packages[title] = prior_pkg
                if prior_receipt is not None:
                    receipts[title] = prior_receipt
                self._packages[title] = packages[title]
            else:
                packages[title] = TitlePackageAcquisition(
                    title=title,
                    disposition=PackageDisposition.MISSING,
                    release_point=None,
                    content_sha256=None,
                    status=TitlePackageStatus.FAILED,
                    verification=VerificationResult.MISSING,
                    notes="resume: no prior package and no fixture redownload",
                )
                self._packages[title] = packages[title]

        expected = prior_result.expected_packages or self.enumerate_expected_packages(
            from_fixture=bool(fixture_packages)
        )
        completeness = build_completeness_report(
            packages,
            expected_titles=self._required_titles,
            notes="Resume acquisition completeness",
            metadata={"mode": CatalogAcquisitionMode.RESUME.value},
        )
        if require_complete and not completeness.is_complete:
            raise CatalogCompletenessError(
                "catalog resume incomplete: "
                f"missing={list(completeness.missing_titles)} "
                f"failed={list(completeness.failed_titles)}"
            )

        result = CatalogAcquisitionResult(
            approved_release=approved,
            packages=packages,
            completeness=completeness,
            mode=CatalogAcquisitionMode.RESUME,
            resume_receipts=receipts,
            proposed_release=prior_result.proposed_release,
            expected_packages=expected,
            currentness_disclaimer=prior_result.currentness_disclaimer,
            schema_version=SCHEMA_VERSION,
            fixture_id=prior_result.fixture_id,
            notes="Resumed catalog acquisition; verified packages not redownloaded",
            metadata={
                "prior_mode": prior_result.mode.value,
                "prior_download_count": prior_result.download_count,
            },
            download_count=download_count,
            skip_count=skip_count,
        )
        self._last_result = result
        self.checkpoint_receipts(result)
        return result

    # -- completeness ------------------------------------------------------

    def completeness_report(
        self,
        packages: Mapping[str, TitlePackageAcquisition] | None = None,
        *,
        require_complete: bool = False,
    ) -> TitleCompletenessReport:
        """Return an explicit title completeness report."""

        if packages is None:
            if self._last_result is not None:
                packages = self._last_result.packages
            else:
                packages = self._packages
        report = build_completeness_report(
            packages, expected_titles=self._required_titles
        )
        if require_complete and not report.is_complete:
            raise CatalogCompletenessError(
                "title completeness failed: "
                f"missing={list(report.missing_titles)} "
                f"failed={list(report.failed_titles)} "
                f"excluded={list(report.excluded_titles)}"
            )
        return report

    def report_missing_and_excluded(
        self,
        packages: Mapping[str, TitlePackageAcquisition] | None = None,
    ) -> dict[str, tuple[str, ...]]:
        """Return ``{"missing": (...), "excluded": (...)}`` title lists."""

        report = self.completeness_report(packages)
        return {
            "missing": report.missing_titles,
            "excluded": report.excluded_titles,
            "failed": report.failed_titles,
        }

    # -- checkpoints -------------------------------------------------------

    def checkpoint_path(self, name: str = "catalog_checkpoint.json") -> Path:
        return Path(self.checkpoint_dir) / name

    def checkpoint_receipts(
        self,
        result: CatalogAcquisitionResult | None = None,
        *,
        path: PathLike | None = None,
    ) -> Path:
        """Atomically write resume receipts and acquisition result to disk."""

        if result is None:
            if self._last_result is None:
                raise CatalogCheckpointError("no acquisition result to checkpoint")
            result = self._last_result

        target = Path(path) if path is not None else self.checkpoint_path()
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "checkpoint_kind": "uscode-release-catalog",
            "approved_release": result.approved_release.to_dict(),
            "completeness": result.completeness.to_dict(),
            "download_count": result.download_count,
            "skip_count": result.skip_count,
            "fixture_id": result.fixture_id,
            "mode": result.mode.value,
            "resume_receipts": {
                k: v.to_dict()
                for k, v in sorted(result.resume_receipts.items(), key=lambda kv: kv[0])
            },
            "packages": {
                k: {
                    "title": v.title,
                    "disposition": v.disposition.value,
                    "release_point": v.release_point,
                    "content_sha256": v.content_sha256,
                    "package_id": v.package_id,
                    "source_url": v.source_url,
                    "status": v.status.value,
                    "verification": v.verification.value,
                    "redownloaded": v.redownloaded,
                    "resume_receipt": (
                        None if v.resume_receipt is None else v.resume_receipt.to_dict()
                    ),
                    "exclusion": None if v.exclusion is None else v.exclusion.to_dict(),
                    "notes": v.notes,
                }
                for k, v in sorted(result.packages.items(), key=lambda kv: kv[0])
            },
            "result": result.to_dict(),
            "result_digest": result.result_digest(),
        }
        _atomic_write_json(target, envelope)
        return target

    def load_checkpoint(self, path: PathLike | None = None) -> CatalogAcquisitionResult:
        """Load a previously written catalog checkpoint."""

        target = Path(path) if path is not None else self.checkpoint_path()
        if not target.is_file():
            raise CatalogCheckpointError(f"checkpoint not found: {target}")
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise CatalogCheckpointError(f"checkpoint root must be a mapping: {target}")
        if "result" in payload:
            return CatalogAcquisitionResult.from_dict(payload["result"])
        return CatalogAcquisitionResult.from_dict(payload)

    # -- binding validation ------------------------------------------------

    def assert_accepted_packages_bound(
        self,
        packages: Mapping[str, TitlePackageAcquisition] | None = None,
    ) -> None:
        """Fail closed when any accepted package lacks checksum or release point."""

        if packages is None:
            packages = self._packages if self._packages else (
                self._last_result.packages if self._last_result else {}
            )
        for title, pkg in packages.items():
            if pkg.disposition in {
                PackageDisposition.ACCEPTED,
                PackageDisposition.SKIPPED_VERIFIED,
            }:
                if not pkg.content_sha256:
                    raise CatalogAcquisitionError(
                        f"accepted package for title {title} missing content_sha256"
                    )
                if not pkg.release_point:
                    raise CatalogAcquisitionError(
                        f"accepted package for title {title} missing release_point"
                    )


__all__ = [
    "CANONICAL_USCODE_TITLES",
    "CURRENTNESS_DISCLAIMER",
    "DEFAULT_APPROVED_RELEASE_POINT",
    "DEFAULT_CATALOG_APPROVED_BY",
    "DEFAULT_FIXTURE_ID",
    "EXPECTED_TITLE_COUNT",
    "FIXTURE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "CatalogAcquisitionError",
    "CatalogAcquisitionMode",
    "CatalogAcquisitionResult",
    "CatalogCheckpointError",
    "CatalogCompletenessError",
    "CatalogFixtureSchemaError",
    "HardCodedLatestEditionError",
    "MissingApprovedReleaseError",
    "PackageDisposition",
    "TitleCompletenessReport",
    "TitlePackageAcquisition",
    "TitlePackageSpec",
    "UnapprovedMixedVintageError",
    "UnapprovedProposedReleaseError",
    "UscodeReleaseCatalog",
    "UscodeReleaseCatalogError",
    "UscodeSourcePolicy",
    "build_completeness_report",
    "build_default_catalog_fixture_payload",
    "canonical_json_dumps",
    "content_sha256",
    "default_catalog_fixture_path",
    "default_checkpoint_directory",
    "digest_mapping",
    "expand_catalog_fixture",
    "expected_title_package_sha256",
    "load_catalog_fixture",
    "load_catalog_fixture_payload",
    "normalize_title",
    "parse_release_point_id",
    "require_canonical_title",
    "titles_missing_from_manifest",
    "ushouse_releasepoint_zip_url",
    "ushouse_title_code",
    "write_default_catalog_fixture",
]
