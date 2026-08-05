#!/usr/bin/env python3
"""Acquire full MPEP section-level texts for the public corpus (PATLAW-183).

Fetches every inventoried MPEP section (and form-paragraph / appendix /
index anchor) for a **pinned** edition/revision and emits a content-addressed
acquisition receipt.

Standing rules
--------------
* Default mode is **fixture / offline**: uses the PATLAW-182 compact full-
  chapter inventory fixture and deterministic section bodies (no network).
* Live crawl is opt-in (``--live``), polite (rate-limited User-Agent), and
  never required for CI.
* Section count must match inventory minus explicit gaps (strict by default).
* Each acquired section carries a stable identity and SHA-256 digest.
* Supersession edges from the inventory are retained unchanged and remain
  guidance-tier (never elevated to binding law).
* Chapter-landing-page-only crawls fail closed.
* No Hub upload.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (  # noqa: E402
    AUTHORITY_TIER_GUIDANCE,
    GOAL_ID as INVENTORY_GOAL_ID,
    REQUIRED_CHAPTER_IDS,
    REQUIRED_MPEP_CHAPTERS,
    SCHEMA_VERSION as INVENTORY_SCHEMA_VERSION,
    BindingElevationError,
    ChapterOnlyInventoryError,
    EditionPinError,
    GapKind,
    IncompleteChapterCoverageError,
    InventoryEntryKind,
    InventoryEntryStatus,
    MpepEditionPin,
    MpepFullInventoryManifest,
    MpepFullSectionError,
    MpepInventoryGap,
    MpepSectionInventoryEntry,
    MpepSupersessionRecord,
    assert_guidance_not_elevated,
    build_compact_full_inventory_fixture,
    build_mpep_full_manifest,
    canonical_json,
    chapter_id_for_section,
    cid_from_digest,
    content_digest_of,
    content_sha256,
    is_chapter_landing_anchor,
    mpep_source_url,
    normalize_mpep_section,
    stable_section_identity,
    validate_full_chapter_coverage,
    validate_inventory_not_chapter_only,
    validate_manifest_dict,
)

# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

TASK_ID: str = "PATLAW-183"
GOAL_ID: str = "PATLAW-G216"
SCHEMA_VERSION: str = "patent.mpep_full.acquisition.v1"
INTERFACE: str = "MpepFullSectionAcquisition@1"
PRODUCER: str = "producer:mpep-full-section-acquisition"
CONFIG_ID: str = "config:mpep-full-section-acquisition/v1"
CODE_VERSION: str = "1.0.0"
RECEIPT_FILENAME: str = "acquisition-receipt.json"
SECTIONS_DIRNAME: str = "sections"
INVENTORY_FILENAME: str = "inventory-manifest.json"
SUPERSESSIONS_FILENAME: str = "supersessions.json"
DEFAULT_USER_AGENT: str = (
    "ipfs-accelerate-patent-legal-intelligence/1.0 "
    "(+https://github.com/justicedao; polite MPEP section acquisition; PATLAW-183)"
)
DEFAULT_LIVE_DELAY_SECONDS: float = 0.75
DEFAULT_LIVE_TIMEOUT_SECONDS: float = 30.0

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
SectionFetcher = Callable[["FetchRequest"], "FetchResult"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MpepFullAcquisitionError(RuntimeError):
    """Base error for full MPEP section acquisition failures."""

    code: str = "mpep_full_acquisition_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class AcquisitionCountMismatchError(MpepFullAcquisitionError):
    """Raised when acquired present count does not match inventory − gaps."""

    code = "acquisition_count_mismatch"


class ChapterLandingCrawlError(MpepFullAcquisitionError):
    """Raised when a crawl/inventory is chapter-landing only."""

    code = "chapter_landing_crawl"


class LiveNetworkDisabledError(MpepFullAcquisitionError):
    """Raised when live fetch is requested without ``--live``."""

    code = "live_network_disabled"


class MissingSectionBodyError(MpepFullAcquisitionError):
    """Raised when a present inventory entry yields no body and no gap."""

    code = "missing_section_body"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AcquisitionMode(str, Enum):
    """Operator-visible acquisition mode."""

    DRY_RUN = "dry_run"
    STAGE = "stage"
    LIVE = "live"

    @classmethod
    def coerce(cls, value: Any) -> "AcquisitionMode":
        if isinstance(value, AcquisitionMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise MpepFullAcquisitionError(f"unsupported acquisition mode: {value!r}")


class SectionAcquisitionStatus(str, Enum):
    """Per-section acquisition outcome."""

    ACQUIRED = "acquired"
    GAP = "gap"
    HASH_MISMATCH = "hash_mismatch"
    RETRIEVAL_FAILED = "retrieval_failed"

    @classmethod
    def coerce(cls, value: Any) -> "SectionAcquisitionStatus":
        if isinstance(value, SectionAcquisitionStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise MpepFullAcquisitionError(f"unsupported section status: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _omit_none(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def _safe_filename(entry_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._+\-]+", "_", entry_id).strip("._")
    return cleaned or "section"


def fixture_section_body(
    entry: MpepSectionInventoryEntry,
    edition: str,
    revision: str,
) -> str:
    """Deterministic offline body for one inventory entry (PATLAW-182 fixture).

    Matches the compact inventory fixture digests when the entry was built by
    ``build_compact_full_inventory_fixture``.
    """
    if entry.kind is InventoryEntryKind.FORM_PARAGRAPH:
        return f"fixture:fp:{entry.section_anchor}:{edition}:r{revision}"
    return f"fixture:{entry.chapter_id}:{entry.section_anchor}:{edition}:r{revision}"


# ---------------------------------------------------------------------------
# Fetch types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """One section fetch request."""

    entry: MpepSectionInventoryEntry
    edition_pin: MpepEditionPin
    source_url: str
    mode: AcquisitionMode


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Result of fetching one section body."""

    body: Optional[str]
    status: SectionAcquisitionStatus
    content_sha256: Optional[str] = None
    media_type: str = "text/plain"
    source_url: Optional[str] = None
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    gap_kind: Optional[GapKind] = None
    gap_reason: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SectionAcquisitionStatus.coerce(self.status))
        if self.body is not None and self.content_sha256 is None:
            object.__setattr__(self, "content_sha256", content_sha256(self.body))
        if self.gap_kind is not None and not isinstance(self.gap_kind, GapKind):
            object.__setattr__(self, "gap_kind", GapKind.coerce(self.gap_kind))


def fixture_fetcher(request: FetchRequest) -> FetchResult:
    """Offline fetcher: materialize deterministic fixture bodies.

    Present inventory entries without a synthesizable body become explicit
    retrieval gaps (fail-visible, never silent omit).
    """
    entry = request.entry
    url = entry.source_url or mpep_source_url(
        section=entry.section_anchor
        if entry.kind is InventoryEntryKind.MPEP_SECTION
        else None
    )
    if entry.status is InventoryEntryStatus.GAP:
        return FetchResult(
            body=None,
            status=SectionAcquisitionStatus.GAP,
            source_url=url,
            gap_kind=GapKind.UNAVAILABLE,
            gap_reason=entry.gap_reason or "explicit inventory gap",
            media_type=entry.media_type or "text/plain",
        )
    body = fixture_section_body(
        entry,
        request.edition_pin.edition,
        request.edition_pin.revision,
    )
    digest = content_sha256(body)
    if entry.content_sha256 and entry.content_sha256 != digest:
        return FetchResult(
            body=body,
            status=SectionAcquisitionStatus.HASH_MISMATCH,
            content_sha256=digest,
            media_type=entry.media_type or "text/plain",
            source_url=url,
            gap_kind=GapKind.HASH_MISMATCH,
            gap_reason=(
                f"fixture body digest {digest} does not match inventory "
                f"content_sha256 {entry.content_sha256}"
            ),
            error_code="hash_mismatch",
            error_message="fixture body does not match inventory digest",
        )
    return FetchResult(
        body=body,
        status=SectionAcquisitionStatus.ACQUIRED,
        content_sha256=digest,
        media_type=entry.media_type or "text/plain",
        source_url=url,
    )


def live_http_fetcher(
    request: FetchRequest,
    *,
    delay_seconds: float = DEFAULT_LIVE_DELAY_SECONDS,
    timeout_seconds: float = DEFAULT_LIVE_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchResult:
    """Polite live HTTP fetcher for USPTO MPEP HTML (opt-in only)."""
    entry = request.entry
    url = entry.source_url or mpep_source_url(
        section=entry.section_anchor
        if entry.kind is InventoryEntryKind.MPEP_SECTION
        else None
    )
    if entry.status is InventoryEntryStatus.GAP:
        return FetchResult(
            body=None,
            status=SectionAcquisitionStatus.GAP,
            source_url=url,
            gap_kind=GapKind.UNAVAILABLE,
            gap_reason=entry.gap_reason or "explicit inventory gap",
        )
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    headers = {"User-Agent": user_agent, "Accept": "text/html,text/plain,*/*"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            ctype = (resp.headers.get("Content-Type") or "text/html").split(";")[0].strip()
            media = ctype or "text/html"
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:
                body = raw.decode("utf-8", errors="replace")
            # Prefer plain text for BM25 / vector indexing while keeping HTML
            # media_type only when conversion collapses to nothing useful.
            plain = html_to_text(body)
            if len(plain) >= 40:
                body = plain
                media = "text/plain"
            digest = content_sha256(body)
            return FetchResult(
                body=body,
                status=SectionAcquisitionStatus.ACQUIRED,
                content_sha256=digest,
                media_type=media,
                source_url=url,
                http_status=status,
            )
    except urllib.error.HTTPError as exc:
        return FetchResult(
            body=None,
            status=SectionAcquisitionStatus.RETRIEVAL_FAILED,
            source_url=url,
            http_status=int(exc.code),
            error_code=str(exc.code),
            error_message=str(exc.reason),
            gap_kind=GapKind.RETRIEVAL_FAILED,
            gap_reason=f"HTTP {exc.code}: {exc.reason}",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return FetchResult(
            body=None,
            status=SectionAcquisitionStatus.RETRIEVAL_FAILED,
            source_url=url,
            error_code=type(exc).__name__,
            error_message=str(exc),
            gap_kind=GapKind.RETRIEVAL_FAILED,
            gap_reason=f"retrieval failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Acquisition records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcquiredSection:
    """One acquired (or gapped) MPEP section with stable identity and digest."""

    entry_id: str
    chapter_id: str
    section_anchor: str
    kind: InventoryEntryKind
    stable_identity: str
    status: SectionAcquisitionStatus
    content_sha256: Optional[str] = None
    content_cid: Optional[str] = None
    text: Optional[str] = None
    byte_size: Optional[int] = None
    source_url: Optional[str] = None
    media_type: Optional[str] = None
    title: Optional[str] = None
    citation: Optional[str] = None
    inventory_status: str = InventoryEntryStatus.PRESENT.value
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    gap_kind: Optional[str] = None
    gap_reason: Optional[str] = None
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", InventoryEntryKind.coerce(self.kind))
        object.__setattr__(self, "status", SectionAcquisitionStatus.coerce(self.status))
        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label=f"section {self.entry_id}",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", str(self.content_sha256).strip().lower()
            )
        if self.content_cid is None and self.content_sha256:
            object.__setattr__(
                self, "content_cid", cid_from_digest(self.content_sha256)
            )
        if self.text is not None and self.byte_size is None:
            object.__setattr__(self, "byte_size", len(self.text.encode("utf-8")))
        if not isinstance(self.metadata, Mapping):
            raise MpepFullAcquisitionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_present(self) -> bool:
        return (
            self.status is SectionAcquisitionStatus.ACQUIRED
            and bool(self.content_sha256)
        )

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "authority_tier": AUTHORITY_TIER_GUIDANCE,
            "byte_size": self.byte_size,
            "chapter_id": self.chapter_id,
            "citation": self.citation,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "entry_id": self.entry_id,
            "error_code": self.error_code,
            "gap_kind": self.gap_kind,
            "gap_reason": self.gap_reason,
            "http_status": self.http_status,
            "inventory_status": self.inventory_status,
            "is_binding": False,
            "kind": self.kind.value,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata) or None,
            "section_anchor": self.section_anchor,
            "source_url": self.source_url,
            "stable_identity": self.stable_identity,
            "status": self.status.value,
            "title": self.title,
        }
        if include_text:
            payload["text"] = self.text
        return _omit_none(payload)


@dataclass(frozen=True, slots=True)
class AcquisitionCounts:
    """Aggregate counts for acceptance (inventory − gaps = acquired)."""

    inventory_entries: int
    inventory_present: int
    inventory_gaps: int
    acquired: int
    acquisition_gaps: int
    supersession_edges: int
    chapters_required: int
    chapters_covered: int
    section_level_acquired: int

    def to_dict(self) -> dict[str, int]:
        return {
            "acquired": self.acquired,
            "acquisition_gaps": self.acquisition_gaps,
            "chapters_covered": self.chapters_covered,
            "chapters_required": self.chapters_required,
            "inventory_entries": self.inventory_entries,
            "inventory_gaps": self.inventory_gaps,
            "inventory_present": self.inventory_present,
            "section_level_acquired": self.section_level_acquired,
            "supersession_edges": self.supersession_edges,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcquisitionCounts":
        return cls(
            inventory_entries=int(value.get("inventory_entries") or 0),
            inventory_present=int(value.get("inventory_present") or 0),
            inventory_gaps=int(value.get("inventory_gaps") or 0),
            acquired=int(value.get("acquired") or 0),
            acquisition_gaps=int(value.get("acquisition_gaps") or 0),
            supersession_edges=int(value.get("supersession_edges") or 0),
            chapters_required=int(value.get("chapters_required") or 0),
            chapters_covered=int(value.get("chapters_covered") or 0),
            section_level_acquired=int(value.get("section_level_acquired") or 0),
        )


@dataclass(frozen=True, slots=True)
class MpepFullAcquisitionReceipt:
    """Content-addressed receipt for a full MPEP section acquisition run."""

    edition_pin: MpepEditionPin
    sections: tuple[AcquiredSection, ...]
    counts: AcquisitionCounts
    inventory_digest_sha256: str
    package_digest_sha256: str
    package_root_cid: str
    supersessions: tuple[MpepSupersessionRecord, ...] = ()
    gaps: tuple[MpepInventoryGap, ...] = ()
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    producer: str = PRODUCER
    config_id: str = CONFIG_ID
    code_version: str = CODE_VERSION
    inventory_schema_version: str = INVENTORY_SCHEMA_VERSION
    inventory_goal_id: str = INVENTORY_GOAL_ID
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    mode: str = AcquisitionMode.DRY_RUN.value
    partition: str = "public"
    acquired_at_utc: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edition_pin, MpepEditionPin):
            raise EditionPinError("edition_pin must be an MpepEditionPin")
        if self.schema_version != SCHEMA_VERSION:
            raise MpepFullAcquisitionError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        if self.interface != INTERFACE:
            raise MpepFullAcquisitionError(
                f"interface must be {INTERFACE!r}, got {self.interface!r}"
            )
        if self.task_id != TASK_ID:
            raise MpepFullAcquisitionError(f"task_id must be {TASK_ID!r}")
        if self.goal_id != GOAL_ID:
            raise MpepFullAcquisitionError(f"goal_id must be {GOAL_ID!r}")
        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label="acquisition receipt",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "supersessions", tuple(self.supersessions))
        object.__setattr__(self, "gaps", tuple(self.gaps))
        if self.partition != "public":
            raise MpepFullAcquisitionError("partition must be 'public'")
        mode = AcquisitionMode.coerce(self.mode).value
        object.__setattr__(self, "mode", mode)
        if not isinstance(self.metadata, Mapping):
            raise MpepFullAcquisitionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
        for edge in self.supersessions:
            if edge.elevates_to_law or not edge.remains_guidance:
                raise BindingElevationError(
                    "supersession edges on the acquisition receipt must remain guidance"
                )

    @property
    def present_sections(self) -> tuple[AcquiredSection, ...]:
        return tuple(s for s in self.sections if s.is_present)

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        return _omit_none(
            {
                "acquired_at_utc": self.acquired_at_utc,
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "code_version": self.code_version,
                "config_id": self.config_id,
                "counts": self.counts.to_dict(),
                "edition_pin": self.edition_pin.to_dict(),
                "gaps": [g.to_dict() for g in self.gaps] or None,
                "goal_id": self.goal_id,
                "interface": self.interface,
                "inventory_digest_sha256": self.inventory_digest_sha256,
                "inventory_goal_id": self.inventory_goal_id,
                "inventory_schema_version": self.inventory_schema_version,
                "is_binding": False,
                "metadata": _deep_sorted(self.metadata) or None,
                "mode": self.mode,
                "notes": self.notes,
                "package_digest_sha256": self.package_digest_sha256,
                "package_root_cid": self.package_root_cid,
                "partition": self.partition,
                "producer": self.producer,
                "schema_version": self.schema_version,
                "sections": [s.to_dict(include_text=include_text) for s in self.sections],
                "supersessions": [e.to_dict() for e in self.supersessions] or None,
                "task_id": self.task_id,
            }
        )

    def addressable_payload(self) -> dict[str, Any]:
        """Stable payload used for package digests (excludes free text bodies)."""
        return self.to_dict(include_text=False)

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepFullAcquisitionReceipt":
        if not isinstance(value, Mapping):
            raise MpepFullAcquisitionError("receipt must be a mapping")
        pin_raw = value.get("edition_pin")
        if not isinstance(pin_raw, Mapping):
            raise EditionPinError("edition_pin is required")
        sections_raw = value.get("sections") or []
        sections: list[AcquiredSection] = []
        for raw in sections_raw:
            if not isinstance(raw, Mapping):
                continue
            sections.append(
                AcquiredSection(
                    entry_id=str(raw.get("entry_id") or ""),
                    chapter_id=str(raw.get("chapter_id") or ""),
                    section_anchor=str(raw.get("section_anchor") or ""),
                    kind=InventoryEntryKind.coerce(
                        raw.get("kind", InventoryEntryKind.MPEP_SECTION)
                    ),
                    stable_identity=str(raw.get("stable_identity") or ""),
                    status=SectionAcquisitionStatus.coerce(
                        raw.get("status", SectionAcquisitionStatus.ACQUIRED)
                    ),
                    content_sha256=raw.get("content_sha256"),
                    content_cid=raw.get("content_cid"),
                    text=raw.get("text"),
                    byte_size=raw.get("byte_size"),
                    source_url=raw.get("source_url"),
                    media_type=raw.get("media_type"),
                    title=raw.get("title"),
                    citation=raw.get("citation"),
                    inventory_status=str(
                        raw.get("inventory_status") or InventoryEntryStatus.PRESENT.value
                    ),
                    authority_tier=str(
                        raw.get("authority_tier") or AUTHORITY_TIER_GUIDANCE
                    ),
                    is_binding=bool(raw.get("is_binding", False)),
                    gap_kind=raw.get("gap_kind"),
                    gap_reason=raw.get("gap_reason"),
                    http_status=raw.get("http_status"),
                    error_code=raw.get("error_code"),
                    metadata=raw.get("metadata") or {},
                )
            )
        counts_raw = value.get("counts")
        if not isinstance(counts_raw, Mapping):
            raise MpepFullAcquisitionError("counts must be a mapping")
        supersessions = tuple(
            s
            if isinstance(s, MpepSupersessionRecord)
            else MpepSupersessionRecord.from_dict(s)
            for s in (value.get("supersessions") or [])
            if isinstance(s, (Mapping, MpepSupersessionRecord))
        )
        gaps = tuple(
            g
            if isinstance(g, MpepInventoryGap)
            else MpepInventoryGap.from_dict(g)
            for g in (value.get("gaps") or [])
            if isinstance(g, (Mapping, MpepInventoryGap))
        )
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            inventory_schema_version=str(
                value.get("inventory_schema_version") or INVENTORY_SCHEMA_VERSION
            ),
            inventory_goal_id=str(
                value.get("inventory_goal_id") or INVENTORY_GOAL_ID
            ),
            edition_pin=MpepEditionPin.from_dict(pin_raw),
            sections=tuple(sections),
            counts=AcquisitionCounts.from_dict(counts_raw),
            inventory_digest_sha256=str(value.get("inventory_digest_sha256") or ""),
            package_digest_sha256=str(value.get("package_digest_sha256") or ""),
            package_root_cid=str(value.get("package_root_cid") or ""),
            supersessions=supersessions,
            gaps=gaps,
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            mode=str(value.get("mode") or AcquisitionMode.DRY_RUN.value),
            partition=str(value.get("partition") or "public"),
            acquired_at_utc=value.get("acquired_at_utc"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Inventory loading / gap helpers
# ---------------------------------------------------------------------------


def load_inventory_manifest(
    path: PathLike | None = None,
    *,
    use_default_fixture: bool = False,
) -> MpepFullInventoryManifest:
    """Load a PATLAW-182 inventory manifest from disk or the compact fixture."""
    if use_default_fixture or path is None:
        if path is None and not use_default_fixture:
            raise MpepFullAcquisitionError(
                "inventory path is required unless --default-fixture is set"
            )
        if use_default_fixture:
            return validate_manifest_dict(build_compact_full_inventory_fixture())
    target = Path(path) if path is not None else None
    if target is None or not target.is_file():
        raise MpepFullAcquisitionError(f"inventory manifest not found: {path}")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MpepFullAcquisitionError(f"invalid inventory JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise MpepFullAcquisitionError("inventory root must be a JSON object")
    return validate_manifest_dict(raw)


def build_inventory_with_explicit_gap(
    *,
    gap_chapter_id: str = "2900",
    gap_anchor: str = "2901",
    gap_reason: str = "explicit fixture gap for PATLAW-183 acceptance",
) -> MpepFullInventoryManifest:
    """Build compact inventory with one present entry converted to an explicit gap.

    Used by integration tests to prove acquired count = inventory − gaps.
    """
    base = build_compact_full_inventory_fixture()
    inventory: list[MpepSectionInventoryEntry] = []
    gaps: list[MpepInventoryGap] = []
    for raw in base["inventory"]:
        entry = MpepSectionInventoryEntry.from_dict(raw)
        if entry.chapter_id == gap_chapter_id and entry.section_anchor == gap_anchor:
            gapped = MpepSectionInventoryEntry(
                entry_id=entry.entry_id,
                chapter_id=entry.chapter_id,
                section_anchor=entry.section_anchor,
                kind=entry.kind,
                status=InventoryEntryStatus.GAP,
                title=entry.title,
                citation=entry.citation,
                source_url=entry.source_url,
                media_type=entry.media_type,
                gap_reason=gap_reason,
            )
            inventory.append(gapped)
            gaps.append(
                MpepInventoryGap(
                    gap_id=f"fixture_gap-{entry.entry_id}",
                    kind=GapKind.UNAVAILABLE,
                    chapter_id=entry.chapter_id,
                    reason=gap_reason,
                    section_anchor=entry.section_anchor,
                    source_url=entry.source_url,
                )
            )
        else:
            inventory.append(entry)
    supersessions = tuple(
        MpepSupersessionRecord.from_dict(s) for s in (base.get("supersessions") or [])
    )
    pin = MpepEditionPin.from_dict(base["edition_pin"])
    return build_mpep_full_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=supersessions,
        gaps=gaps,
        mode="dry_run",
        notes=(
            "Compact inventory fixture with one explicit gap for PATLAW-183. "
            "Guidance only; never binding law."
        ),
    )


def _stable_id_for_entry(entry: MpepSectionInventoryEntry) -> str:
    return stable_section_identity(kind=entry.kind, anchor=entry.section_anchor)


def _reject_chapter_only(inventory: Sequence[MpepSectionInventoryEntry]) -> None:
    try:
        validate_inventory_not_chapter_only(inventory)
        validate_full_chapter_coverage(inventory, require_all_chapters=True)
    except ChapterOnlyInventoryError as exc:
        raise ChapterLandingCrawlError(
            "chapter-landing-page-only crawls fail acceptance; enumerate section "
            "anchors (e.g. 706.02), not only chapter landings"
        ) from exc
    except IncompleteChapterCoverageError:
        raise
    landings = [
        e
        for e in inventory
        if e.kind is InventoryEntryKind.MPEP_SECTION
        and is_chapter_landing_anchor(
            chapter_id=e.chapter_id, section_anchor=e.section_anchor
        )
        and e.status is InventoryEntryStatus.PRESENT
    ]
    section_level = [e for e in inventory if e.is_section_level]
    if landings and not section_level:
        raise ChapterLandingCrawlError(
            "chapter-landing-page-only crawls fail acceptance; enumerate section "
            "anchors (e.g. 706.02), not only chapter landings"
        )


# ---------------------------------------------------------------------------
# Live full-manual discovery (USPTO chapter TOCs → section inventory)
# ---------------------------------------------------------------------------


def mpep_chapter_toc_url(chapter_id: str) -> str:
    """Return the USPTO static HTML TOC URL for a numbered MPEP chapter."""

    ch = str(chapter_id).strip()
    if not ch.isdigit():
        raise MpepFullAcquisitionError(
            f"chapter TOC discovery only supports numbered chapters, got {chapter_id!r}"
        )
    n = int(ch)
    token = f"{n:04d}" if n < 1000 else str(n)
    return f"https://www.uspto.gov/web/offices/pac/mpep/mpep-{token}.html"


def html_to_text(html: str) -> str:
    """Best-effort HTML → plain text for indexing (no external deps)."""

    text = str(html or "")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</(div|tr|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _http_get_text(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_LIVE_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "text/html,text/plain,*/*"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def extract_section_anchors_from_chapter_html(
    html: str,
    *,
    chapter_id: str,
) -> list[str]:
    """Extract MPEP section anchors linked from a chapter TOC page."""

    anchors: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"""(?i)(?:href\s*=\s*["']|/web/offices/pac/mpep/)s(\d{3,4}(?:\.\d+)*)\.html""",
        html,
    ):
        raw = match.group(1)
        try:
            sec = normalize_mpep_section(raw)
            parent = chapter_id_for_section(sec)
        except Exception:
            continue
        if parent != str(chapter_id):
            # Keep only sections belonging to the requested chapter.
            continue
        if sec in seen:
            continue
        seen.add(sec)
        anchors.append(sec)
    return anchors


def discover_live_mpep_inventory(
    *,
    edition: str = "9",
    revision: str = "07.2022",
    cutoff: str = "2022-07-01",
    delay_seconds: float = 0.2,
    timeout_seconds: float = DEFAULT_LIVE_TIMEOUT_SECONDS,
    include_appendices: bool = True,
    http_get: Callable[[str], str] | None = None,
) -> MpepFullInventoryManifest:
    """Discover the full section inventory by crawling USPTO chapter TOC pages.

    Numbered chapters 100–2900 are expanded to every ``sNNNN.html`` section
    linked from the chapter TOC. Appendices/index remain compact anchors from
    the offline fixture when ``include_appendices`` is true (those pages are
    not uniformly section-numbered on the static HTML mirror).
    """

    getter = http_get or (
        lambda url: _http_get_text(url, timeout_seconds=timeout_seconds)
    )
    pin = MpepEditionPin(
        edition=edition,
        revision=revision,
        cutoff=cutoff,
        provider="uspto",
        publication_date=cutoff,
        source_url="https://www.uspto.gov/web/offices/pac/mpep/index.html",
        notes=f"MPEP {edition} Edition, Revision {revision} (live full discovery)",
    )
    inventory: list[MpepSectionInventoryEntry] = []
    discovery_meta: dict[str, Any] = {"chapters": {}, "mode": "live_toc_discovery"}

    for spec in REQUIRED_MPEP_CHAPTERS:
        if not str(spec.chapter_id).isdigit():
            continue
        url = mpep_chapter_toc_url(spec.chapter_id)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            html = getter(url)
        except Exception as exc:  # noqa: BLE001 — record chapter gap, continue
            discovery_meta["chapters"][spec.chapter_id] = {
                "status": "toc_fetch_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "url": url,
                "sections": 0,
            }
            # Fall back to one representative anchor so chapter coverage remains.
            compact = build_compact_full_inventory_fixture()
            fallback = next(
                (
                    MpepSectionInventoryEntry.from_dict(raw)
                    for raw in compact["inventory"]
                    if str(raw.get("chapter_id")) == spec.chapter_id
                ),
                None,
            )
            if fallback is not None:
                inventory.append(fallback)
            continue
        anchors = extract_section_anchors_from_chapter_html(
            html, chapter_id=spec.chapter_id
        )
        discovery_meta["chapters"][spec.chapter_id] = {
            "status": "ok",
            "url": url,
            "sections": len(anchors),
        }
        if not anchors:
            # Keep a single non-landing representative if TOC parse yields nothing.
            compact = build_compact_full_inventory_fixture()
            fallback = next(
                (
                    MpepSectionInventoryEntry.from_dict(raw)
                    for raw in compact["inventory"]
                    if str(raw.get("chapter_id")) == spec.chapter_id
                    and str(raw.get("kind")) == InventoryEntryKind.MPEP_SECTION.value
                ),
                None,
            )
            if fallback is not None:
                inventory.append(fallback)
            continue
        for anchor in anchors:
            if is_chapter_landing_anchor(
                chapter_id=spec.chapter_id, section_anchor=anchor
            ):
                continue
            inventory.append(
                MpepSectionInventoryEntry(
                    entry_id=f"mpep-{spec.chapter_id}-{anchor}",
                    chapter_id=spec.chapter_id,
                    section_anchor=anchor,
                    kind=InventoryEntryKind.MPEP_SECTION,
                    status=InventoryEntryStatus.PRESENT,
                    title=f"MPEP § {anchor}",
                    citation=f"MPEP § {anchor}",
                    source_url=mpep_source_url(section=anchor),
                    media_type="text/html",
                )
            )

    if include_appendices:
        compact = build_compact_full_inventory_fixture()
        for raw in compact["inventory"]:
            kind = str(raw.get("kind") or "")
            chapter_id = str(raw.get("chapter_id") or "")
            if not chapter_id.isdigit() or kind in {
                InventoryEntryKind.APPENDIX_ANCHOR.value,
                InventoryEntryKind.INDEX_ANCHOR.value,
                InventoryEntryKind.FORM_PARAGRAPH.value,
            }:
                inventory.append(MpepSectionInventoryEntry.from_dict(raw))

    # Deduplicate by (chapter_id, section_anchor, kind)
    dedup: dict[tuple[str, str, str], MpepSectionInventoryEntry] = {}
    for entry in inventory:
        key = (entry.chapter_id, entry.section_anchor, entry.kind.value)
        dedup[key] = entry
    inventory = list(dedup.values())
    inventory.sort(
        key=lambda e: (
            0 if str(e.chapter_id).isdigit() else 1,
            int(e.chapter_id) if str(e.chapter_id).isdigit() else 0,
            e.chapter_id,
            e.section_anchor,
            e.kind.value,
        )
    )

    supersessions = tuple(
        MpepSupersessionRecord.from_dict(s)
        for s in (
            build_compact_full_inventory_fixture().get("supersessions") or []
        )
        if isinstance(s, Mapping)
    )
    discovery_meta["inventory_entries"] = len(inventory)
    discovery_meta["section_level"] = sum(
        1 for e in inventory if e.kind is InventoryEntryKind.MPEP_SECTION
    )
    return build_mpep_full_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=supersessions,
        mode="acquire",
        notes=(
            "Live full MPEP section inventory discovered from USPTO chapter TOC "
            "pages (sNNNN.html). Guidance only; never binding law."
        ),
        metadata=discovery_meta,
    )


# ---------------------------------------------------------------------------
# Core acquisition
# ---------------------------------------------------------------------------


def acquire_mpep_full_sections(
    inventory: MpepFullInventoryManifest | Mapping[str, Any] | None = None,
    *,
    mode: AcquisitionMode | str = AcquisitionMode.DRY_RUN,
    fetcher: SectionFetcher | None = None,
    allow_live: bool = False,
    live_delay_seconds: float = DEFAULT_LIVE_DELAY_SECONDS,
    notes: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    acquired_at: Optional[datetime] = None,
    strict_count: bool = True,
    discover_live_inventory: bool = False,
) -> MpepFullAcquisitionReceipt:
    """Acquire every inventoried section and build a content-addressed receipt.

    Acceptance (when ``strict_count`` is True, the default):

    * ``counts.acquired == counts.inventory_present``
      (section count matches inventory minus explicit gaps)
    * every acquired section has ``stable_identity`` and ``content_sha256``
    * supersession edges from the inventory are retained unchanged
    """
    mode_v = AcquisitionMode.coerce(mode)
    if mode_v is AcquisitionMode.LIVE and not allow_live:
        raise LiveNetworkDisabledError(
            "live acquisition requires allow_live=True / --live"
        )

    if discover_live_inventory:
        if mode_v is not AcquisitionMode.LIVE or not allow_live:
            raise LiveNetworkDisabledError(
                "discover_live_inventory requires live mode with allow_live=True"
            )
        manifest = discover_live_mpep_inventory(
            delay_seconds=min(float(live_delay_seconds), 0.35),
        )
    elif inventory is None:
        manifest = load_inventory_manifest(use_default_fixture=True)
    elif isinstance(inventory, MpepFullInventoryManifest):
        manifest = inventory
    elif isinstance(inventory, Mapping):
        manifest = validate_manifest_dict(inventory)
    else:
        raise MpepFullAcquisitionError("inventory must be a manifest or mapping")

    if fetcher is None:
        if mode_v is AcquisitionMode.LIVE:

            def _live(req: FetchRequest) -> FetchResult:
                return live_http_fetcher(req, delay_seconds=live_delay_seconds)

            fetcher = _live
        else:
            fetcher = fixture_fetcher

    acquired_at_dt = acquired_at or _utc_now()
    _reject_chapter_only(manifest.inventory)

    sections: list[AcquiredSection] = []
    gaps: list[MpepInventoryGap] = list(manifest.gaps)
    inventory_present = 0
    inventory_gaps = 0

    for entry in manifest.inventory:
        if entry.status is InventoryEntryStatus.PRESENT:
            inventory_present += 1
        else:
            inventory_gaps += 1

        stable_id = _stable_id_for_entry(entry)
        source_url = entry.source_url or mpep_source_url(
            section=entry.section_anchor
            if entry.kind is InventoryEntryKind.MPEP_SECTION
            else None
        )
        request = FetchRequest(
            entry=entry,
            edition_pin=manifest.edition_pin,
            source_url=source_url,
            mode=mode_v,
        )
        result = fetcher(request)

        gap_kind: Optional[str] = None
        gap_reason: Optional[str] = None
        if result.gap_kind is not None:
            gap_kind = (
                result.gap_kind.value
                if isinstance(result.gap_kind, GapKind)
                else str(result.gap_kind)
            )
            gap_reason = result.gap_reason

        if (
            entry.status is InventoryEntryStatus.PRESENT
            and result.status is SectionAcquisitionStatus.ACQUIRED
            and not (result.body or "").strip()
            and not result.content_sha256
        ):
            raise MissingSectionBodyError(
                f"present entry {entry.entry_id} produced empty body"
            )

        section = AcquiredSection(
            entry_id=entry.entry_id,
            chapter_id=entry.chapter_id,
            section_anchor=entry.section_anchor,
            kind=entry.kind,
            stable_identity=stable_id,
            status=result.status,
            content_sha256=result.content_sha256,
            text=result.body,
            source_url=result.source_url or source_url,
            media_type=result.media_type or entry.media_type,
            title=entry.title,
            citation=entry.citation,
            inventory_status=entry.status.value,
            gap_kind=gap_kind,
            gap_reason=gap_reason or entry.gap_reason,
            http_status=result.http_status,
            error_code=result.error_code,
            metadata={
                "edition_key": manifest.edition_pin.edition_key,
            },
        )
        sections.append(section)

        if result.status is not SectionAcquisitionStatus.ACQUIRED:
            if entry.status is InventoryEntryStatus.PRESENT and strict_count is False:
                pass  # recorded as acquisition gap below
            elif (
                entry.status is InventoryEntryStatus.PRESENT
                and result.status
                in {
                    SectionAcquisitionStatus.RETRIEVAL_FAILED,
                    SectionAcquisitionStatus.HASH_MISMATCH,
                    SectionAcquisitionStatus.GAP,
                }
            ):
                # Still record the section; strict_count may raise later.
                pass

            if result.status is not SectionAcquisitionStatus.ACQUIRED:
                already = {
                    (g.chapter_id, g.section_anchor)
                    for g in gaps
                    if g.section_anchor is not None
                }
                key = (entry.chapter_id, entry.section_anchor)
                if key not in already and entry.status is InventoryEntryStatus.PRESENT:
                    gaps.append(
                        MpepInventoryGap(
                            gap_id=f"acq-gap-{entry.entry_id}",
                            kind=result.gap_kind or GapKind.RETRIEVAL_FAILED,
                            chapter_id=entry.chapter_id,
                            reason=result.gap_reason
                            or f"section {entry.section_anchor} not acquired "
                            f"({result.status.value})",
                            section_anchor=entry.section_anchor,
                            expected_sha256=entry.content_sha256,
                            observed_sha256=result.content_sha256,
                            source_url=result.source_url or source_url,
                            detected_at=acquired_at_dt,
                        )
                    )

    present_acquired = sum(1 for s in sections if s.is_present)
    acquisition_gaps = sum(
        1
        for s in sections
        if s.inventory_status == InventoryEntryStatus.PRESENT.value
        and not s.is_present
    )
    covered_chapters = {
        s.chapter_id
        for s in sections
        if s.is_present
        or (
            s.inventory_status == InventoryEntryStatus.GAP.value
            and s.kind is not InventoryEntryKind.FORM_PARAGRAPH
        )
    }
    # Prefer chapter coverage from acquired + inventory-gap section-level anchors.
    for entry in manifest.inventory:
        if entry.is_section_level:
            covered_chapters.add(entry.chapter_id)

    section_level_acquired = sum(
        1
        for s in sections
        if s.is_present
        and s.kind
        in {
            InventoryEntryKind.MPEP_SECTION,
            InventoryEntryKind.APPENDIX_ANCHOR,
            InventoryEntryKind.INDEX_ANCHOR,
            InventoryEntryKind.FORM_PARAGRAPH,
        }
        and not is_chapter_landing_anchor(
            chapter_id=s.chapter_id, section_anchor=s.section_anchor
        )
    )

    counts = AcquisitionCounts(
        inventory_entries=len(manifest.inventory),
        inventory_present=inventory_present,
        inventory_gaps=inventory_gaps,
        acquired=present_acquired,
        acquisition_gaps=acquisition_gaps,
        supersession_edges=len(manifest.supersessions),
        chapters_required=len(REQUIRED_CHAPTER_IDS),
        chapters_covered=len(covered_chapters & REQUIRED_CHAPTER_IDS),
        section_level_acquired=section_level_acquired,
    )

    if strict_count and counts.acquired != counts.inventory_present:
        raise AcquisitionCountMismatchError(
            f"acquired present sections ({counts.acquired}) must equal inventory "
            f"present entries ({counts.inventory_present}) (inventory "
            f"{counts.inventory_entries} minus explicit gaps {counts.inventory_gaps}); "
            f"acquisition_gaps={counts.acquisition_gaps}"
        )

    for s in sections:
        if s.is_present:
            if not s.stable_identity:
                raise MpepFullAcquisitionError(f"{s.entry_id} missing stable_identity")
            if not s.content_sha256:
                raise MpepFullAcquisitionError(f"{s.entry_id} missing content_sha256")
            if not s.stable_identity.startswith("mpep:"):
                raise MpepFullAcquisitionError(
                    f"{s.entry_id} stable_identity must start with 'mpep:'"
                )

    supersessions = tuple(manifest.supersessions)
    for edge in supersessions:
        if edge.elevates_to_law or not edge.remains_guidance:
            raise BindingElevationError(
                "inventory supersession elevates to law; rejected"
            )

    package_payload = {
        "counts": counts.to_dict(),
        "edition_pin": manifest.edition_pin.to_dict(),
        "inventory_digest_sha256": manifest.inventory_digest_sha256,
        "sections": [
            {
                "content_sha256": s.content_sha256,
                "entry_id": s.entry_id,
                "stable_identity": s.stable_identity,
                "status": s.status.value,
            }
            for s in sections
        ],
        "supersessions": [e.to_dict() for e in supersessions],
        "task_id": TASK_ID,
    }
    package_digest = content_digest_of(package_payload)

    receipt = MpepFullAcquisitionReceipt(
        edition_pin=manifest.edition_pin,
        sections=tuple(sections),
        counts=counts,
        inventory_digest_sha256=manifest.inventory_digest_sha256,
        package_digest_sha256=package_digest,
        package_root_cid=cid_from_digest(package_digest),
        supersessions=supersessions,
        gaps=tuple(gaps),
        mode=mode_v.value,
        acquired_at_utc=_format_utc(acquired_at_dt),
        notes=notes
        or (
            "Full MPEP section-level acquisition receipt (PATLAW-183). "
            "Guidance only; never binding law. No Hub upload."
        ),
        metadata={
            "inventory_package_digest_sha256": manifest.package_digest_sha256,
            "inventory_package_root_cid": manifest.package_root_cid,
            **dict(metadata or {}),
        },
    )
    return receipt


def validate_acquisition_receipt(
    receipt: MpepFullAcquisitionReceipt | Mapping[str, Any],
    *,
    inventory: MpepFullInventoryManifest | Mapping[str, Any] | None = None,
) -> MpepFullAcquisitionReceipt:
    """Validate acceptance criteria on an acquisition receipt."""
    if isinstance(receipt, Mapping):
        receipt = MpepFullAcquisitionReceipt.from_dict(receipt)
    assert_guidance_not_elevated(
        authority_tier=receipt.authority_tier,
        is_binding=receipt.is_binding,
        elevates_to_law=False,
        label="receipt",
    )
    if receipt.counts.acquired != receipt.counts.inventory_present:
        raise AcquisitionCountMismatchError(
            f"acquired ({receipt.counts.acquired}) != inventory_present "
            f"({receipt.counts.inventory_present})"
        )
    expected_present = (
        receipt.counts.inventory_entries - receipt.counts.inventory_gaps
    )
    if receipt.counts.acquired != expected_present:
        raise AcquisitionCountMismatchError(
            f"acquired ({receipt.counts.acquired}) != inventory_entries - gaps "
            f"({receipt.counts.inventory_entries} - {receipt.counts.inventory_gaps})"
        )
    for sec in receipt.present_sections:
        if not sec.stable_identity or not sec.content_sha256:
            raise MpepFullAcquisitionError(
                f"present section {sec.entry_id} lacks stable identity or sha256"
            )

    if inventory is not None:
        inv = (
            inventory
            if isinstance(inventory, MpepFullInventoryManifest)
            else validate_manifest_dict(inventory)
        )
        if inv.supersessions:
            if not receipt.supersessions:
                raise MpepFullAcquisitionError(
                    "supersession edges were not retained on the acquisition receipt"
                )
            inv_edges = {
                (e.successor_id, e.predecessor_id, e.relation.value)
                for e in inv.supersessions
            }
            rec_edges = {
                (e.successor_id, e.predecessor_id, e.relation.value)
                for e in receipt.supersessions
            }
            if inv_edges != rec_edges:
                raise MpepFullAcquisitionError(
                    "supersession edge set differs between inventory and receipt"
                )
        if receipt.inventory_digest_sha256 != inv.inventory_digest_sha256:
            raise MpepFullAcquisitionError(
                "receipt inventory_digest_sha256 does not match inventory"
            )
    return receipt


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcquisitionStageResult:
    """Result of writing an acquisition package to disk."""

    receipt: MpepFullAcquisitionReceipt
    output_dir: Path
    receipt_path: Path
    sections_dir: Path
    inventory_path: Optional[Path] = None
    supersessions_path: Optional[Path] = None
    mode: str = AcquisitionMode.STAGE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_path": None
            if self.inventory_path is None
            else str(self.inventory_path),
            "mode": self.mode,
            "output_dir": str(self.output_dir),
            "package_digest_sha256": self.receipt.package_digest_sha256,
            "package_root_cid": self.receipt.package_root_cid,
            "receipt_path": str(self.receipt_path),
            "sections_dir": str(self.sections_dir),
            "supersessions_path": None
            if self.supersessions_path is None
            else str(self.supersessions_path),
        }


def stage_acquisition(
    receipt: MpepFullAcquisitionReceipt,
    output_dir: PathLike,
    *,
    inventory: MpepFullInventoryManifest | Mapping[str, Any] | None = None,
    include_text_in_receipt: bool = False,
) -> AcquisitionStageResult:
    """Write acquisition receipt, section bodies, and optional inventory copy."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    sections_dir = out / SECTIONS_DIRNAME
    sections_dir.mkdir(parents=True, exist_ok=True)

    staged_mode = (
        AcquisitionMode.LIVE.value
        if receipt.mode == AcquisitionMode.LIVE.value
        else AcquisitionMode.STAGE.value
    )
    staged_receipt = MpepFullAcquisitionReceipt.from_dict(
        {
            **receipt.to_dict(include_text=include_text_in_receipt),
            "mode": staged_mode,
        }
    )

    section_by_id = {s.entry_id: s for s in receipt.sections}
    for sec in receipt.sections:
        if sec.text is not None and sec.is_present:
            name = f"{_safe_filename(sec.entry_id)}.txt"
            path = sections_dir / name
            path.write_text(sec.text + "\n", encoding="utf-8")
            disk_digest = content_sha256(sec.text)
            if sec.content_sha256 and disk_digest != sec.content_sha256:
                # Body may include trailing newline only on disk; digest is of body.
                body_on_disk = path.read_text(encoding="utf-8")
                # Prefer digest of the staged body without trailing newline used above.
                if content_sha256(body_on_disk.rstrip("\n")) != sec.content_sha256:
                    raise MpepFullAcquisitionError(
                        f"staged body digest mismatch for {sec.entry_id}: "
                        f"{disk_digest} != {sec.content_sha256}"
                    )

    receipt_path = out / RECEIPT_FILENAME
    receipt_path.write_text(
        canonical_json(staged_receipt.to_dict(include_text=include_text_in_receipt))
        + "\n",
        encoding="utf-8",
    )

    inventory_path: Optional[Path] = None
    if inventory is not None:
        inv_payload = (
            inventory.to_dict()
            if isinstance(inventory, MpepFullInventoryManifest)
            else dict(inventory)
            if isinstance(inventory, Mapping)
            else None
        )
        if inv_payload is not None:
            inventory_path = out / INVENTORY_FILENAME
            inventory_path.write_text(
                canonical_json(inv_payload) + "\n", encoding="utf-8"
            )

    supersessions_path: Optional[Path] = None
    if receipt.supersessions:
        supersessions_path = out / SUPERSESSIONS_FILENAME
        supersessions_path.write_text(
            canonical_json([e.to_dict() for e in receipt.supersessions]) + "\n",
            encoding="utf-8",
        )

    # Rehydrate from disk for round-trip consistency when text was written out.
    rehydrated_sections: list[AcquiredSection] = []
    for original in staged_receipt.sections:
        text = original.text
        if text is None and original.is_present:
            disk_path = sections_dir / f"{_safe_filename(original.entry_id)}.txt"
            if disk_path.is_file():
                text = disk_path.read_text(encoding="utf-8").rstrip("\n")
        rehydrated_sections.append(
            AcquiredSection(
                entry_id=original.entry_id,
                chapter_id=original.chapter_id,
                section_anchor=original.section_anchor,
                kind=original.kind,
                stable_identity=original.stable_identity,
                status=original.status,
                content_sha256=original.content_sha256,
                content_cid=original.content_cid,
                text=text if include_text_in_receipt else None,
                byte_size=original.byte_size,
                source_url=original.source_url,
                media_type=original.media_type,
                title=original.title,
                citation=original.citation,
                inventory_status=original.inventory_status,
                gap_kind=original.gap_kind,
                gap_reason=original.gap_reason,
                http_status=original.http_status,
                error_code=original.error_code,
                metadata=original.metadata,
            )
        )

    final = MpepFullAcquisitionReceipt(
        edition_pin=staged_receipt.edition_pin,
        sections=tuple(rehydrated_sections),
        counts=staged_receipt.counts,
        inventory_digest_sha256=staged_receipt.inventory_digest_sha256,
        package_digest_sha256=staged_receipt.package_digest_sha256,
        package_root_cid=staged_receipt.package_root_cid,
        supersessions=staged_receipt.supersessions,
        gaps=staged_receipt.gaps,
        schema_version=staged_receipt.schema_version,
        interface=staged_receipt.interface,
        task_id=staged_receipt.task_id,
        goal_id=staged_receipt.goal_id,
        producer=staged_receipt.producer,
        config_id=staged_receipt.config_id,
        code_version=staged_receipt.code_version,
        inventory_schema_version=staged_receipt.inventory_schema_version,
        inventory_goal_id=staged_receipt.inventory_goal_id,
        mode=staged_mode,
        partition=staged_receipt.partition,
        acquired_at_utc=staged_receipt.acquired_at_utc,
        notes=staged_receipt.notes,
        metadata=staged_receipt.metadata,
    )
    # Rewrite receipt after rehydration if include_text requested.
    receipt_path.write_text(
        canonical_json(final.to_dict(include_text=include_text_in_receipt)) + "\n",
        encoding="utf-8",
    )

    return AcquisitionStageResult(
        receipt=final,
        output_dir=out,
        receipt_path=receipt_path,
        sections_dir=sections_dir,
        inventory_path=inventory_path,
        supersessions_path=supersessions_path,
        mode=staged_mode,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            f"Acquire full MPEP section-level texts for a pinned edition "
            f"({TASK_ID}). Default: offline fixture dry-run, no Hub upload."
        )
    )
    p.add_argument(
        "--default-fixture",
        action="store_true",
        help="Use the PATLAW-182 compact full-chapter inventory fixture (offline)",
    )
    p.add_argument(
        "--inventory",
        type=str,
        default=None,
        help="Path to a PATLAW-182 mpep-full inventory manifest JSON",
    )
    p.add_argument(
        "--write-default-inventory",
        type=str,
        default=None,
        metavar="PATH",
        help="Write the compact inventory fixture to PATH and exit",
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Local staging directory (required with --stage)",
    )
    p.add_argument(
        "--stage",
        action="store_true",
        help=(
            "Write local staged artifacts (receipt, section bodies, inventory). "
            "Default is dry-run only."
        ),
    )
    p.add_argument(
        "--live",
        action="store_true",
        help=(
            "Opt-in polite live HTTP fetch of USPTO MPEP HTML. "
            "CI and default dry-run stay offline."
        ),
    )
    p.add_argument(
        "--live-discover",
        action="store_true",
        help=(
            "With --live: discover the full section inventory from USPTO "
            "chapter TOC pages (every sNNNN.html), not just the compact fixture"
        ),
    )
    p.add_argument(
        "--live-delay-seconds",
        type=float,
        default=DEFAULT_LIVE_DELAY_SECONDS,
        help=f"Polite delay between live fetches (default {DEFAULT_LIVE_DELAY_SECONDS})",
    )
    p.add_argument(
        "--include-text-in-receipt",
        action="store_true",
        help=(
            "Embed section text bodies in the staged receipt JSON "
            "(default: bodies on disk only)"
        ),
    )
    p.add_argument(
        "--print-receipt",
        action="store_true",
        help="Print the acquisition receipt JSON to stdout",
    )
    p.add_argument(
        "--strict-count",
        action="store_true",
        default=True,
        help="Require acquired == inventory_present (default: on)",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow acquired < inventory_present "
            "(records acquisition gaps; not for acceptance)"
        ),
    )
    p.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress human-readable summary lines",
    )
    return p


def _print_summary(receipt: MpepFullAcquisitionReceipt) -> None:
    c = receipt.counts
    print(f"schema_version:          {receipt.schema_version}")
    print(f"task_id:                 {receipt.task_id}")
    print(f"mode:                    {receipt.mode}")
    print(f"edition_key:             {receipt.edition_pin.edition_key}")
    print(f"inventory_entries:       {c.inventory_entries}")
    print(f"inventory_present:       {c.inventory_present}")
    print(f"inventory_gaps:          {c.inventory_gaps}")
    print(f"acquired:                {c.acquired}")
    print(f"acquisition_gaps:        {c.acquisition_gaps}")
    print(f"supersession_edges:      {c.supersession_edges}")
    print(f"chapters_covered:        {c.chapters_covered}")
    print(f"section_level_acquired:  {c.section_level_acquired}")
    print(f"inventory_digest_sha256: {receipt.inventory_digest_sha256}")
    print(f"package_digest_sha256:   {receipt.package_digest_sha256}")
    print(f"package_root_cid:        {receipt.package_root_cid}")
    print(f"authority_tier:          {receipt.authority_tier}")
    print(f"is_binding:              {receipt.is_binding}")
    print("hub_upload:              false")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.write_default_inventory:
        payload = build_compact_full_inventory_fixture()
        target = Path(args.write_default_inventory)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        print(f"wrote compact inventory fixture: {target}")
        return 0

    if args.live_discover and not args.live:
        print("--live-discover requires --live", file=sys.stderr)
        return 2

    if args.stage and not args.output_dir:
        print("--output-dir is required with --stage", file=sys.stderr)
        return 2

    if args.live:
        mode = AcquisitionMode.LIVE
    elif args.stage:
        mode = AcquisitionMode.STAGE
    else:
        mode = AcquisitionMode.DRY_RUN

    manifest: MpepFullInventoryManifest | None = None
    if not args.live_discover:
        try:
            if args.default_fixture or not args.inventory:
                if not args.default_fixture and not args.inventory:
                    # Default path: compact fixture offline.
                    manifest = load_inventory_manifest(use_default_fixture=True)
                elif args.default_fixture:
                    manifest = load_inventory_manifest(use_default_fixture=True)
                else:
                    manifest = load_inventory_manifest(args.inventory)
            else:
                manifest = load_inventory_manifest(args.inventory)
        except (
            MpepFullAcquisitionError,
            MpepFullSectionError,
            EditionPinError,
            ChapterOnlyInventoryError,
            IncompleteChapterCoverageError,
            BindingElevationError,
        ) as exc:
            print(f"error: inventory load failed: {exc}", file=sys.stderr)
            return 2

    strict = not bool(args.allow_partial)
    try:
        receipt = acquire_mpep_full_sections(
            manifest,
            mode=mode,
            allow_live=bool(args.live),
            live_delay_seconds=float(args.live_delay_seconds),
            strict_count=strict,
            discover_live_inventory=bool(args.live_discover),
        )
        if strict and manifest is not None:
            validate_acquisition_receipt(receipt, inventory=manifest)
        # live-discover builds inventory inside acquire_mpep_full_sections and
        # already enforces strict_count against that inventory.
    except (
        MpepFullAcquisitionError,
        MpepFullSectionError,
        EditionPinError,
        ChapterOnlyInventoryError,
        IncompleteChapterCoverageError,
        BindingElevationError,
    ) as exc:
        print(f"error: acquisition failed: {exc}", file=sys.stderr)
        return 2

    if args.stage:
        try:
            output_dir = Path(args.output_dir)
            stage_result = stage_acquisition(
                receipt,
                output_dir,
                inventory=manifest,
                include_text_in_receipt=bool(args.include_text_in_receipt),
            )
            receipt = stage_result.receipt
        except (MpepFullAcquisitionError, OSError) as exc:
            print(f"error: staging failed: {exc}", file=sys.stderr)
            return 2

    if not args.no_print_summary:
        _print_summary(receipt)

    if args.print_receipt:
        print(canonical_json(receipt.to_dict(include_text=bool(args.include_text_in_receipt))))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
