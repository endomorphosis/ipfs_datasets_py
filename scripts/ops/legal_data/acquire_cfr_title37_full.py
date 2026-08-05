#!/usr/bin/env python3
"""Acquire full annual CFR Title 37 text package for the public corpus (PATLAW-181).

Materializes a **pinned** official GovInfo annual Title 37 package into:

* a full part/section inventory (every catalog section present or explicit gap)
* content digests for sections that have text
* package-level ``sha256`` / CIDv1 bindings
* an acquisition receipt (no Hub upload)

Default path is **offline fixture replay** of the bounded Title 37 GovInfo
annual recipe under ``tests/fixtures/legal_data/patent_authorities/cfr/``.
Live GovInfo network acquisition is opt-in (``--live``) and never required
for CI.

Design invariants
-----------------
* Edition identity is always concrete (``year`` + ``CFR-YYYY-title37``).
  The hard-coded token ``latest`` is rejected.
* Inventory enumerates the full Title 37 catalog from PATLAW-180 contracts.
  Sections without acquired text receive first-class gap records; omission
  is not allowed.
* Package bindings use the **official annual** GovInfo package digests.
  eCFR-only partial crawls do **not** complete this task (fail closed).
* Authority tier remains ``official-base``; eCFR is at most a linked
  presentation identity and never substitutes for annual package completion.
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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Optional, Sequence, Union
from xml.etree import ElementTree as ET

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (  # noqa: E402
    DEFAULT_TITLE,
    GOAL_ID as INVENTORY_GOAL_ID,
    MANIFEST_FILENAME,
    SCHEMA_VERSION as INVENTORY_SCHEMA_VERSION,
    TASK_ID as INVENTORY_TASK_ID,
    TITLE37_PART_METADATA,
    TITLE37_PARTS,
    TITLE37_SECTION_CATALOG,
    CfrTitle37FullError,
    CfrTitle37FullManifest,
    EditionIdentity,
    EmptyInventoryError,
    GapReason,
    GapRecord,
    InventorySectionEntry,
    MaterializationMode,
    MissingEditionIdentityError,
    PackageBinding,
    PackageBindingError,
    SectionPresence,
    UnpinnedLatestError,
    build_gap_records_for_inventory,
    content_digest_of,
    content_sha256,
    title37_section_count,
    validate_manifest,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (  # noqa: E402
    content_address_bytes,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.cfr_annual_processor import (  # noqa: E402
    CfrAnnualAcquisition,
    CfrAnnualProcessor,
    MissingPackageError,
    default_fixture_dir as cfr_default_fixture_dir,
    govinfo_cfr_package_id,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (  # noqa: E402
    normalize_part_token,
    normalize_section_token,
)

# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

ACQUIRE_TASK_ID: Final = "PATLAW-181"
ACQUIRE_GOAL_ID: Final = "PATLAW-G215"
ACQUIRE_SCHEMA_VERSION: Final = "patent.cfr_title37_full.acquisition.v1"
ACQUIRE_PRODUCER: Final = "producer:cfr-title37-full-acquire"
ACQUIRE_CONFIG_ID: Final = "config:cfr-title37-full-acquire/v1"
ACQUIRE_CODE_VERSION: Final = "1.0.0"
RECEIPT_FILENAME: Final = "cfr-title37-full.acquisition.receipt.json"
PACKAGE_META_FILENAME: Final = "package_meta.json"
SECTIONS_DIRNAME: Final = "sections"
DEFAULT_FIXTURE_RELPATH: Final = (
    "tests/fixtures/legal_data/patent_authorities/cfr/cfr_annual_recipe.json"
)
# Live package download uses volume-scoped GovInfo package ids
# (``CFR-YYYY-title37-volN``). Identity remains the unscoped
# ``CFR-YYYY-title37`` pin from PATLAW-180 contracts.
GOVINFO_CONTENT_BASE: Final = "https://www.govinfo.gov/content/pkg"
DEFAULT_HTTP_TIMEOUT_SECONDS: Final = 120.0
DEFAULT_LIVE_MAX_VOLUMES: Final = 4
DEFAULT_LIVE_VOLUME_DELAY_SECONDS: Final = 0.25
_USER_AGENT: Final = (
    "ipfs-datasets-py-patent-legal-intelligence/1.0 "
    "(+https://github.com/endomorphosis/ipfs_datasets_py; "
    "public-domain CFR acquisition)"
)
_MONTHS: Final = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_SECTION_NUM_RE = re.compile(
    r"(?P<section>\d+(?:\.\d+)*(?:[A-Za-z]+)?)",
)
# Cap expanded reserved ranges (e.g. §§ 11.508-11.700) to keep materialization bounded.
_MAX_RANGE_EXPANSION: Final = 500

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
HttpGetter = Callable[[str, float], bytes]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CfrTitle37AcquireError(RuntimeError):
    """Base error for Title 37 full-package acquisition failures."""

    code: str = "cfr_title37_acquire_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class EcfrOnlyAcquisitionError(CfrTitle37AcquireError):
    """Raised when eCFR-only material is offered as annual package completion."""

    code = "ecfr_only_rejected"


class LiveAcquisitionUnavailableError(CfrTitle37AcquireError):
    """Raised when live GovInfo acquisition is requested but unavailable."""

    code = "live_acquisition_unavailable"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CfrTitle37AcquisitionResult:
    """Outcome of a full Title 37 annual package acquisition."""

    manifest: CfrTitle37FullManifest
    receipt: Mapping[str, Any]
    section_texts: Mapping[str, str]
    source_kind: str
    fixture_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    package_meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def package_id(self) -> str:
        return self.manifest.edition_identity.package_id

    @property
    def package_digest_sha256(self) -> str:
        return self.manifest.package_binding.package_digest_sha256

    @property
    def package_root_cid(self) -> Optional[str]:
        return self.manifest.package_binding.package_root_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_path": None if self.fixture_path is None else str(self.fixture_path),
            "manifest": self.manifest.to_dict(),
            "output_dir": None if self.output_dir is None else str(self.output_dir),
            "package_meta": dict(self.package_meta),
            "receipt": dict(self.receipt),
            "section_count_present": sum(
                1
                for e in self.manifest.inventory
                if e.presence is SectionPresence.PRESENT
            ),
            "section_count_gap": sum(
                1 for e in self.manifest.inventory if e.presence is SectionPresence.GAP
            ),
            "section_texts_keys": sorted(self.section_texts.keys()),
            "source_kind": self.source_kind,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_fixture_path(repo_root: Optional[PathLike] = None) -> Path:
    """Return the default bounded annual Title 37 GovInfo fixture path."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    candidate = root / DEFAULT_FIXTURE_RELPATH
    if candidate.is_file():
        return candidate
    fixture_dir = cfr_default_fixture_dir()
    recipe = fixture_dir / "cfr_annual_recipe.json"
    if recipe.is_file():
        return recipe
    return candidate


def cid_for_sha256(digest: str) -> str:
    """Stable CIDv1 binding for a known content SHA-256 hex digest."""

    text = str(digest).strip().lower()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise PackageBindingError(
            f"package digest must be lowercase 64-char hex SHA-256, got {digest!r}"
        )
    return content_address_bytes(bytes.fromhex(text)).cid


def _section_filename(section: str) -> str:
    token = normalize_section_token(section)
    return f"{token.replace('.', '-')}.txt"


def _govinfo_granule_id(*, package_id: str, part: str, section: str) -> str:
    """Conventional GovInfo granule id for a Title 37 section."""

    sec = normalize_section_token(section).replace(".", "-")
    p = normalize_part_token(part)
    return f"{package_id}-part{p}-sec{sec}"


def _load_json_object(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CfrTitle37AcquireError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CfrTitle37AcquireError(f"expected JSON object in {path}")
    return dict(payload)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def assert_not_ecfr_only(
    payload: Mapping[str, Any] | None = None,
    *,
    source_kind: str | None = None,
    package_present: bool | None = None,
) -> None:
    """Fail closed when eCFR-only material is offered as annual completion.

    eCFR is an unofficial presentation surface. Annual CFR Title 37 completion
    requires the official GovInfo annual package identity and bindings.
    """

    kind = (source_kind or "").strip().lower()
    if kind in {"ecfr", "ecfr-only", "ecfr_only", "ecfr-partial", "ecfr_partial"}:
        raise EcfrOnlyAcquisitionError(
            "eCFR-only / eCFR-partial crawls do not complete annual CFR Title 37 "
            "acquisition; pin an official GovInfo package (CFR-YYYY-title37)"
        )

    if payload is None:
        if package_present is False:
            raise EcfrOnlyAcquisitionError(
                "missing official annual GovInfo package; eCFR presentation alone "
                "does not complete PATLAW-181"
            )
        return

    has_package = bool(
        payload.get("package")
        or payload.get("annual_package")
        or payload.get("release")
    )
    if package_present is not None:
        has_package = bool(package_present)

    ecfr_only_flag = bool(
        payload.get("ecfr_only")
        or payload.get("ecfr-only")
        or str(payload.get("source_kind", "")).lower()
        in {"ecfr", "ecfr-only", "ecfr_only"}
    )
    has_ecfr = bool(
        payload.get("ecfr_presentation")
        or payload.get("ecfr_presentation_sha256")
        or payload.get("derived_presentation")
    )

    if ecfr_only_flag or (has_ecfr and not has_package):
        raise EcfrOnlyAcquisitionError(
            "eCFR-only materialization rejected: official annual GovInfo package "
            "identity (package_id + digests) is required; eCFR presentation is "
            "not a substitute for annual CFR Title 37 completion"
        )

    if not has_package:
        raise EcfrOnlyAcquisitionError(
            "official annual package block is required; refusing eCFR-only or "
            "package-less acquisition for PATLAW-181"
        )


def _edition_from_package(package: Mapping[str, Any]) -> EditionIdentity:
    year = package.get("year")
    package_id = package.get("package_id") or package.get("govinfo_package_id")
    if year in (None, "") and package_id:
        # Derive year from package_id via EditionIdentity.
        return EditionIdentity.from_dict(
            {
                "package_id": package_id,
                "year": "",
                "date_issued": package.get("date_issued"),
                "volume": package.get("volume", "1"),
                "edition": package.get("edition") or "",
                "provider": package.get("provider") or "govinfo",
            }
        )
    if year in (None, ""):
        raise MissingEditionIdentityError(
            "annual package requires year or package_id for edition identity"
        )
    return EditionIdentity.for_year(
        year,
        date_issued=package.get("date_issued"),
        volume=str(package.get("volume") or "1"),
    )


def _package_digests_from_acquisition(
    acquisition: CfrAnnualAcquisition,
) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return (package_digest, xml, pdf, mods, source_url) from annual acquisition."""

    if acquisition.package is None:
        raise MissingPackageError("annual acquisition has no package")
    pkg = acquisition.package
    package_digest = pkg.content_sha256 or acquisition.official_artifact_sha256()
    if not package_digest:
        raise PackageBindingError(
            "official annual package requires package_digest_sha256 / content_sha256"
        )
    xml_sha = None
    pdf_sha = None
    mods_sha = None
    formats = dict(pkg.formats or {})
    if "xml" in formats:
        xml_sha = formats["xml"].artifact_sha256
    if "pdf" in formats:
        pdf_sha = formats["pdf"].artifact_sha256
    if "mods" in formats:
        mods_sha = formats["mods"].artifact_sha256
    if xml_sha is None and package_digest:
        xml_sha = package_digest
    source_url = pkg.source_url
    return package_digest, xml_sha, pdf_sha, mods_sha, source_url


def _section_text_and_digest(
    acquisition: CfrAnnualAcquisition,
) -> dict[str, tuple[str, str]]:
    """Map section token -> (text, sha256) for sections with acquired text."""

    out: dict[str, tuple[str, str]] = {}
    for section, record in acquisition.sections.items():
        text = (record.text_excerpt or "").strip()
        if not text:
            # Prefer an artifact digest-bound placeholder only when formats exist.
            formats = record.formats or {}
            xml = formats.get("xml")
            if xml is not None and xml.artifact_sha256:
                # Synthetic stable text proxy for digest binding when excerpt omitted.
                text = (
                    f"[official annual granule 37 CFR {section}; "
                    f"sha256={xml.artifact_sha256}]"
                )
            else:
                continue
        digest = content_sha256(text)
        # Prefer artifact sha when available for content binding stability.
        formats = record.formats or {}
        xml = formats.get("xml")
        if xml is not None and xml.artifact_sha256:
            digest = xml.artifact_sha256
        out[normalize_section_token(section)] = (text, digest)
    return out


def _part_for_section_token(section: str) -> str | None:
    """Return catalog part for a dotted section token when known."""

    token = normalize_section_token(section)
    if not token or "." not in token:
        # Try exact membership across catalog parts (rare undotted forms).
        for part, secs in TITLE37_SECTION_CATALOG.items():
            if token in secs:
                return part
        return None
    head = token.split(".", 1)[0]
    if head in TITLE37_PART_METADATA:
        return head
    return None


def _build_inventory_with_texts(
    identity: EditionIdentity,
    *,
    section_digests: Mapping[str, str],
    section_urls: Mapping[str, str] | None = None,
    include_edition_extras: bool = False,
) -> tuple[InventorySectionEntry, ...]:
    """Full catalog inventory; present when digest known, else gap.

    When ``include_edition_extras`` is true (live annual packages), also emit
    present rows for package sections under known Title 37 parts that are not
    in the static catalog. Catalog coverage remains mandatory; extras are an
    edition-specific superset allowed by the inventory contract.
    """

    urls = dict(section_urls or {})
    entries: list[InventorySectionEntry] = []
    catalog_sections: set[str] = set()
    for part in TITLE37_PARTS:
        meta = TITLE37_PART_METADATA[part]
        for section in TITLE37_SECTION_CATALOG[part]:
            catalog_sections.add(section)
            granule = _govinfo_granule_id(
                package_id=identity.package_id, part=part, section=section
            )
            default_url = (
                f"https://www.govinfo.gov/content/pkg/"
                f"{identity.package_id}/xml/{granule}.xml"
            )
            if section in section_digests:
                entries.append(
                    InventorySectionEntry(
                        part=part,
                        section=section,
                        heading=meta.get("heading", ""),
                        chapter=meta.get("chapter", ""),
                        granule_id=granule,
                        presence=SectionPresence.PRESENT,
                        content_sha256=section_digests[section],
                        source_url=urls.get(section, default_url),
                    )
                )
            else:
                entries.append(
                    InventorySectionEntry(
                        part=part,
                        section=section,
                        heading=meta.get("heading", ""),
                        chapter=meta.get("chapter", ""),
                        granule_id=granule,
                        presence=SectionPresence.GAP,
                        source_url=default_url,
                    )
                )

    if include_edition_extras:
        extras = sorted(
            sec
            for sec in section_digests
            if sec not in catalog_sections and _part_for_section_token(sec)
        )
        for section in extras:
            part = _part_for_section_token(section)
            if part is None:
                continue
            meta = TITLE37_PART_METADATA[part]
            granule = _govinfo_granule_id(
                package_id=identity.package_id, part=part, section=section
            )
            default_url = (
                f"https://www.govinfo.gov/content/pkg/"
                f"{identity.package_id}/xml/{granule}.xml"
            )
            entries.append(
                InventorySectionEntry(
                    part=part,
                    section=section,
                    heading=meta.get("heading", ""),
                    chapter=meta.get("chapter", ""),
                    granule_id=granule,
                    presence=SectionPresence.PRESENT,
                    content_sha256=section_digests[section],
                    source_url=urls.get(section, default_url),
                )
            )

    if not entries:
        raise EmptyInventoryError("Title 37 catalog produced an empty inventory")
    return tuple(entries)


def _gap_records_for(
    inventory: Sequence[InventorySectionEntry],
    *,
    reason: GapReason = GapReason.NOT_IN_PACKAGE,
    note: str = "",
) -> tuple[GapRecord, ...]:
    default_note = note or (
        "Section inventoried without acquired annual package text "
        "(bounded fixture granule missing or not-in-package)"
    )
    return build_gap_records_for_inventory(
        inventory, reason=reason, note=default_note
    )


def _build_receipt(
    *,
    manifest: CfrTitle37FullManifest,
    source_kind: str,
    fixture_path: Optional[Path],
    output_dir: Optional[Path],
    present_with_text: int,
    gap_count: int,
    notes: str,
) -> dict[str, Any]:
    binding = manifest.package_binding
    counts = manifest.counts
    assert counts is not None
    return {
        "schema_version": ACQUIRE_SCHEMA_VERSION,
        "task_id": ACQUIRE_TASK_ID,
        "goal_id": ACQUIRE_GOAL_ID,
        "producer": ACQUIRE_PRODUCER,
        "config_id": ACQUIRE_CONFIG_ID,
        "code_version": ACQUIRE_CODE_VERSION,
        "inventory_task_id": INVENTORY_TASK_ID,
        "inventory_schema_version": INVENTORY_SCHEMA_VERSION,
        "inventory_goal_id": INVENTORY_GOAL_ID,
        "mode": manifest.mode.value,
        "source_kind": source_kind,
        "authority_tier": manifest.edition_identity.authority_tier,
        "edition_identity": manifest.edition_identity.to_dict(),
        "package_binding": binding.to_dict(),
        "package_id": binding.package_id,
        "package_digest_sha256": binding.package_digest_sha256,
        "package_root_cid": binding.package_root_cid,
        "inventory_digest_sha256": manifest.inventory_digest_sha256,
        "manifest_digest_sha256": manifest.content_digest(),
        "counts": counts.to_dict(),
        "present_sections": counts.present_sections,
        "gap_sections": counts.gap_sections,
        "present_with_text": present_with_text,
        "gap_count": gap_count,
        "catalog_section_count": title37_section_count(),
        "full_inventory": True,
        "ecfr_only_rejected": True,
        "hub_upload": False,
        "fixture_path": None if fixture_path is None else str(fixture_path),
        "output_dir": None if output_dir is None else str(output_dir),
        "manifest_filename": MANIFEST_FILENAME,
        "receipt_filename": RECEIPT_FILENAME,
        "notes": notes,
    }


def _stage_outputs(
    *,
    output_dir: Path,
    manifest: CfrTitle37FullManifest,
    receipt: Mapping[str, Any],
    section_texts: Mapping[str, str],
    package_meta: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_dir / MANIFEST_FILENAME, manifest.to_dict())
    _atomic_write_json(output_dir / RECEIPT_FILENAME, dict(receipt))
    _atomic_write_json(output_dir / PACKAGE_META_FILENAME, dict(package_meta))
    sections_dir = output_dir / SECTIONS_DIRNAME
    sections_dir.mkdir(parents=True, exist_ok=True)
    for section, text in sorted(section_texts.items()):
        _atomic_write_text(sections_dir / _section_filename(section), text)


# ---------------------------------------------------------------------------
# Live GovInfo annual package (volume XML)
# ---------------------------------------------------------------------------


def govinfo_volume_package_id(year: str | int, volume: int, *, title: str = DEFAULT_TITLE) -> str:
    """Return volume-scoped GovInfo package id for annual Title N XML."""

    y = str(year).strip()
    if not y or y.casefold() == "latest":
        raise UnpinnedLatestError("live acquisition requires a concrete calendar year")
    if int(volume) < 1:
        raise CfrTitle37AcquireError(f"volume must be >= 1, got {volume!r}")
    return f"CFR-{y}-title{title}-vol{int(volume)}"


def govinfo_volume_xml_url(year: str | int, volume: int, *, title: str = DEFAULT_TITLE) -> str:
    package_id = govinfo_volume_package_id(year, volume, title=title)
    return f"{GOVINFO_CONTENT_BASE}/{package_id}/xml/{package_id}.xml"


def _parse_govinfo_amddate(raw: str) -> str | None:
    """Parse ``July 1, 2024`` / ISO dates into YYYY-MM-DD."""

    text = str(raw or "").strip()
    if not text:
        return None
    # ISO first
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    m = re.match(
        r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})$",
        text,
    )
    if not m:
        return None
    month = _MONTHS.get(m.group("month").casefold())
    if month is None:
        return None
    day = int(m.group("day"))
    year = int(m.group("year"))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _looks_like_html(payload: bytes) -> bool:
    head = payload[:256].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def default_http_get(url: str, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> bytes:
    """HTTP GET for live GovInfo package bytes (operator path)."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/xml,text/xml,*/*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status >= 400:
                raise LiveAcquisitionUnavailableError(
                    f"GovInfo GET {url} returned HTTP {status}"
                )
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise LiveAcquisitionUnavailableError(
            f"GovInfo GET {url} failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise LiveAcquisitionUnavailableError(
            f"GovInfo GET {url} failed: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise LiveAcquisitionUnavailableError(
            f"GovInfo GET {url} timed out after {timeout}s"
        ) from exc
    if not data:
        raise LiveAcquisitionUnavailableError(f"GovInfo GET {url} returned empty body")
    if _looks_like_html(data):
        raise LiveAcquisitionUnavailableError(
            f"GovInfo GET {url} returned HTML (package/volume not available as XML)"
        )
    return data


def _element_local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _element_text_content(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text and element.text.strip():
        parts.append(element.text.strip())
    for child in element:
        child_text = _element_text_content(child)
        if child_text:
            parts.append(child_text)
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return " ".join(parts)


def extract_section_number(sectno_text: str) -> str | None:
    """Normalize a CFR ``SECTNO`` label to a catalog section token."""

    cleaned = (
        str(sectno_text or "")
        .replace("\u2009", " ")
        .replace("\u00a0", " ")
        .replace("§", " ")
        .strip()
    )
    if not cleaned:
        return None
    # Prefer full token via shared normalizer when possible.
    try:
        token = normalize_section_token(cleaned)
        if token:
            return token
    except Exception:
        pass
    match = _SECTION_NUM_RE.search(cleaned)
    if not match:
        return None
    return normalize_section_token(match.group("section"))


def expand_section_range_token(token: str) -> list[str]:
    """Expand reserved-range SECTNO labels into individual section tokens.

    GovInfo annual XML often uses compact reserved markers such as
    ``§§ 1.106-1.108 [Reserved]``. The catalog inventories each number
    separately, so a single range label must fan out to every integer leaf
    in the inclusive span (same dotted prefix).

    Non-range tokens are returned unchanged. Pathological spans larger than
    :data:`_MAX_RANGE_EXPANSION` are left unexpanded.
    """

    try:
        normalized = normalize_section_token(token)
    except Exception:
        normalized = str(token or "").strip()
    if not normalized or "-" not in normalized:
        return [normalized] if normalized else []
    if normalized.count("-") != 1:
        return [normalized]
    left_raw, right_raw = normalized.split("-", 1)
    try:
        left = normalize_section_token(left_raw)
        right = normalize_section_token(right_raw)
    except Exception:
        return [normalized]
    left_parts = left.split(".")
    right_parts = right.split(".")
    if len(left_parts) != len(right_parts) or left_parts[:-1] != right_parts[:-1]:
        return [normalized]
    try:
        start = int(left_parts[-1])
        end = int(right_parts[-1])
    except ValueError:
        return [normalized]
    if end < start or (end - start) > _MAX_RANGE_EXPANSION:
        return [normalized]
    prefix = ".".join(left_parts[:-1])
    expanded: list[str] = []
    for number in range(start, end + 1):
        token_out = f"{prefix}.{number}" if prefix else str(number)
        expanded.append(normalize_section_token(token_out))
    return expanded or [normalized]


def parse_cfr_volume_xml(
    xml_bytes: bytes,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Parse GovInfo annual CFR volume XML into section texts + metadata.

    Returns
    -------
    sections:
        Map of normalized section token -> plain-text body (includes leaves
        expanded from reserved-range SECTNO labels).
    metadata:
        Optional keys such as ``amddate_raw`` / ``date_issued``.
    direct_sections:
        Section tokens that appeared as standalone SECTNO labels (not only
        via range expansion). Used for edition-specific inventory extras.
    """

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CfrTitle37AcquireError(f"invalid CFR volume XML: {exc}") from exc

    sections: dict[str, str] = {}
    metadata: dict[str, str] = {}
    direct_sections: set[str] = set()

    for element in root.iter():
        name = _element_local_name(element.tag).upper()
        if name == "AMDDATE" and element.text:
            metadata["amddate_raw"] = element.text.strip()
            parsed = _parse_govinfo_amddate(element.text)
            if parsed:
                metadata["date_issued"] = parsed
        if name != "SECTION":
            continue
        sectno_text = ""
        subject = ""
        for child in element:
            child_name = _element_local_name(child.tag).upper()
            if child_name == "SECTNO":
                sectno_text = _element_text_content(child)
            elif child_name == "SUBJECT":
                subject = _element_text_content(child)
        section = extract_section_number(sectno_text)
        if not section:
            continue
        body = _element_text_content(element).strip()
        if subject and body and not body.lower().startswith(subject.lower()[:20]):
            body = f"{subject}\n\n{body}".strip()
        elif subject and not body:
            body = subject
        if not body:
            continue
        # Fan out reserved-range labels onto every catalog leaf they cover.
        expanded_tokens = expand_section_range_token(section)
        if len(expanded_tokens) == 1 and "-" not in expanded_tokens[0]:
            direct_sections.add(expanded_tokens[0])
        for expanded in expanded_tokens:
            previous = sections.get(expanded)
            if previous is None or len(body) > len(previous):
                sections[expanded] = body

    if not sections:
        raise CfrTitle37AcquireError(
            "CFR volume XML contained no parseable SECTION/SECTNO entries"
        )
    return sections, metadata, direct_sections


def download_govinfo_title37_volumes(
    year: str | int,
    *,
    title: str = DEFAULT_TITLE,
    max_volumes: int = DEFAULT_LIVE_MAX_VOLUMES,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    delay_seconds: float = DEFAULT_LIVE_VOLUME_DELAY_SECONDS,
    http_get: HttpGetter | None = None,
) -> list[dict[str, Any]]:
    """Download successive annual Title 37 volume XMLs until unavailable.

    Volume 1 is required. Subsequent volumes are optional; HTML/404 ends the
    scan. Returns a list of dicts with volume metadata and raw bytes.
    """

    getter = http_get or default_http_get
    volumes: list[dict[str, Any]] = []
    for volume in range(1, int(max_volumes) + 1):
        url = govinfo_volume_xml_url(year, volume, title=title)
        if volume > 1 and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            payload = getter(url, timeout)
        except LiveAcquisitionUnavailableError:
            if volume == 1:
                raise
            break
        if not payload or _looks_like_html(payload):
            if volume == 1:
                raise LiveAcquisitionUnavailableError(
                    f"GovInfo GET {url} returned HTML or empty body "
                    "(package/volume not available as XML)"
                )
            break
        digest = content_sha256(payload)
        volumes.append(
            {
                "volume": volume,
                "package_id": govinfo_volume_package_id(year, volume, title=title),
                "source_url": url,
                "content_sha256": digest,
                "byte_size": len(payload),
                "payload": payload,
            }
        )
    if not volumes:
        raise LiveAcquisitionUnavailableError(
            f"no GovInfo volume XML available for CFR-{year}-title{title}"
        )
    return volumes


def acquire_from_govinfo_live(
    *,
    year: str | int,
    mode: MaterializationMode | str = MaterializationMode.ACQUIRE,
    output_dir: PathLike | None = None,
    stage: bool = False,
    require_full_catalog: bool = True,
    notes: str = "",
    max_volumes: int = DEFAULT_LIVE_MAX_VOLUMES,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    delay_seconds: float = DEFAULT_LIVE_VOLUME_DELAY_SECONDS,
    http_get: HttpGetter | None = None,
) -> CfrTitle37AcquisitionResult:
    """Acquire full Title 37 inventory from live GovInfo annual volume XML.

    Downloads ``CFR-YYYY-title37-volN`` XML packages, parses every SECTION into
    plain text, maps present granules onto the full PATLAW-180 catalog, and
    records explicit gaps for catalog rows without package text.
    """

    identity = EditionIdentity.for_year(year)
    volumes = download_govinfo_title37_volumes(
        identity.year,
        title=identity.title,
        max_volumes=max_volumes,
        timeout=timeout,
        delay_seconds=delay_seconds,
        http_get=http_get,
    )

    section_texts: dict[str, str] = {}
    direct_sections: set[str] = set()
    date_issued = identity.date_issued
    for volume in volumes:
        parsed_sections, metadata, volume_direct = parse_cfr_volume_xml(
            volume["payload"]
        )
        if metadata.get("date_issued") and not date_issued:
            date_issued = metadata["date_issued"]
        direct_sections.update(volume_direct)
        for section, text in parsed_sections.items():
            previous = section_texts.get(section)
            if previous is None or len(text) > len(previous):
                section_texts[section] = text

    catalog_sections = {
        normalize_section_token(sec)
        for part in TITLE37_PARTS
        for sec in TITLE37_SECTION_CATALOG[part]
    }
    # Keep catalog-mapped text (including reserved-range expansions) plus
    # standalone edition-specific SECTNO labels under known Title 37 parts.
    keep_sections = set(catalog_sections) | {
        sec
        for sec in direct_sections
        if sec in section_texts and _part_for_section_token(sec) is not None
    }
    section_texts = {
        sec: text
        for sec, text in section_texts.items()
        if sec in keep_sections and text.strip()
    }
    if not section_texts:
        raise LiveAcquisitionUnavailableError(
            "live GovInfo volumes parsed but no catalog sections were present"
        )

    section_digests = {
        sec: content_sha256(text) for sec, text in section_texts.items()
    }
    section_urls = {
        sec: (
            f"{GOVINFO_CONTENT_BASE}/{identity.package_id}/xml/"
            f"{_govinfo_granule_id(package_id=identity.package_id, part=sec.split('.', 1)[0], section=sec)}.xml"
        )
        for sec in section_texts
    }

    # Primary package digest binds the concatenation of volume digests so the
    # multi-volume annual materialization remains content-addressed even when
    # the unscoped package_id has no direct XML URL.
    volume_digest_material = "\n".join(
        f"{item['package_id']}:{item['content_sha256']}" for item in volumes
    ).encode("utf-8")
    package_digest = content_sha256(volume_digest_material)
    # Prefer vol1 content hash as xml_sha256 (actual annual XML artifact).
    xml_sha = str(volumes[0]["content_sha256"])
    package_cid = cid_for_sha256(package_digest)
    source_url = str(volumes[0]["source_url"])

    # Refresh edition identity with concrete date_issued when discovered.
    if date_issued and date_issued != identity.date_issued:
        identity = EditionIdentity(
            year=identity.year,
            package_id=identity.package_id,
            title=identity.title,
            edition=identity.edition,
            provider=identity.provider,
            collection=identity.collection,
            date_issued=date_issued,
            volume=identity.volume,
            authority_tier=identity.authority_tier,
        )

    inventory = _build_inventory_with_texts(
        identity,
        section_digests=section_digests,
        section_urls=section_urls,
        include_edition_extras=True,
    )
    gaps = _gap_records_for(
        inventory,
        reason=GapReason.NOT_IN_PACKAGE,
        note=(
            "Section inventoried without text in live GovInfo annual volume "
            "XML materialization"
        ),
    )
    binding = PackageBinding(
        package_id=identity.package_id,
        package_digest_sha256=package_digest,
        package_root_cid=package_cid,
        xml_sha256=xml_sha,
        inventory_digest_sha256=content_digest_of(
            [e.to_dict() for e in inventory]
        ),
        source_url=source_url,
    )

    mode_value = (
        mode
        if isinstance(mode, MaterializationMode)
        else MaterializationMode(str(mode).strip().lower())
    )
    manifest = CfrTitle37FullManifest(
        edition_identity=identity,
        inventory=inventory,
        package_binding=binding,
        gaps=gaps,
        mode=mode_value,
        current_through=identity.date_issued,
        notes=notes
        or (
            f"Full annual Title 37 acquisition for {identity.package_id} from "
            f"live GovInfo volume XML "
            f"({', '.join(item['package_id'] for item in volumes)}); "
            f"official-base package pin (not eCFR). "
            f"Present granules={len(section_texts)}; gaps={len(gaps)}."
        ),
    )
    if require_full_catalog:
        manifest.assert_full_catalog_coverage()
    validate_manifest(manifest, require_full_catalog=require_full_catalog)

    package_meta: dict[str, Any] = {
        "package_id": identity.package_id,
        "year": identity.year,
        "title": identity.title,
        "provider": identity.provider,
        "authority_tier": identity.authority_tier,
        "package_digest_sha256": package_digest,
        "package_root_cid": package_cid,
        "source_url": binding.source_url,
        "source_kind": "govinfo-annual-live",
        "volume_count": len(volumes),
        "volumes": [
            {
                "volume": item["volume"],
                "package_id": item["package_id"],
                "source_url": item["source_url"],
                "content_sha256": item["content_sha256"],
                "byte_size": item["byte_size"],
            }
            for item in volumes
        ],
        "section_granules_present": sorted(section_texts.keys()),
        "xml_sha256": xml_sha,
        "date_issued": identity.date_issued,
    }

    out_path = Path(output_dir) if output_dir is not None else None
    receipt = _build_receipt(
        manifest=manifest,
        source_kind="govinfo-annual-live",
        fixture_path=None,
        output_dir=out_path if stage else None,
        present_with_text=len(section_texts),
        gap_count=len(gaps),
        notes=manifest.notes,
    )
    receipt["live_network"] = True
    receipt["volume_count"] = len(volumes)
    receipt["volumes"] = package_meta["volumes"]

    if stage:
        if out_path is None:
            raise CfrTitle37AcquireError("--output-dir is required when staging")
        _stage_outputs(
            output_dir=out_path,
            manifest=manifest,
            receipt=receipt,
            section_texts=section_texts,
            package_meta=package_meta,
        )

    return CfrTitle37AcquisitionResult(
        manifest=manifest,
        receipt=receipt,
        section_texts=section_texts,
        source_kind="govinfo-annual-live",
        fixture_path=None,
        output_dir=out_path if stage else None,
        package_meta=package_meta,
    )


def acquire_from_govinfo_fixture(
    fixture_path: PathLike | None = None,
    *,
    mode: MaterializationMode | str = MaterializationMode.ACQUIRE,
    output_dir: PathLike | None = None,
    stage: bool = False,
    require_full_catalog: bool = True,
    notes: str = "",
) -> CfrTitle37AcquisitionResult:
    """Acquire full Title 37 inventory from an official annual GovInfo fixture.

    The bounded CI fixture may only include a subset of section granules; every
    catalog section is still inventoried with ``presence=present`` (text bound)
    or an explicit gap record. eCFR-only payloads are rejected.
    """

    path = Path(fixture_path) if fixture_path is not None else default_fixture_path()
    if not path.is_file():
        raise CfrTitle37AcquireError(f"annual Title 37 fixture not found: {path}")

    payload = _load_json_object(path)
    assert_not_ecfr_only(payload, source_kind="govinfo-annual-fixture")

    processor = CfrAnnualProcessor(fixture_dir=path.parent)
    acquisition = processor.acquire_from_fixture(path, register=False)
    if acquisition.package is None:
        raise EcfrOnlyAcquisitionError(
            "fixture produced no official annual package; eCFR-only / missing "
            "package cannot complete PATLAW-181"
        )

    identity = _edition_from_package(acquisition.package.to_dict())
    (
        package_digest,
        xml_sha,
        pdf_sha,
        mods_sha,
        source_url,
    ) = _package_digests_from_acquisition(acquisition)
    package_cid = cid_for_sha256(package_digest)

    text_map = _section_text_and_digest(acquisition)
    section_digests = {sec: digest for sec, (_text, digest) in text_map.items()}
    section_texts = {sec: text for sec, (text, _digest) in text_map.items()}
    section_urls: dict[str, str] = {}
    for sec, record in acquisition.sections.items():
        formats = record.formats or {}
        xml = formats.get("xml")
        if xml is not None and xml.source_url:
            section_urls[normalize_section_token(sec)] = xml.source_url

    inventory = _build_inventory_with_texts(
        identity,
        section_digests=section_digests,
        section_urls=section_urls,
    )
    gaps = _gap_records_for(inventory)
    binding = PackageBinding(
        package_id=identity.package_id,
        package_digest_sha256=package_digest,
        package_root_cid=package_cid,
        xml_sha256=xml_sha,
        pdf_sha256=pdf_sha,
        mods_sha256=mods_sha,
        inventory_digest_sha256=content_digest_of(
            [e.to_dict() for e in inventory]
        ),
        source_url=source_url
        or (
            f"https://www.govinfo.gov/content/pkg/"
            f"{identity.package_id}/xml/{identity.package_id}.xml"
        ),
    )

    mode_value = (
        mode
        if isinstance(mode, MaterializationMode)
        else MaterializationMode(str(mode).strip().lower())
    )
    manifest = CfrTitle37FullManifest(
        edition_identity=identity,
        inventory=inventory,
        package_binding=binding,
        gaps=gaps,
        mode=mode_value,
        current_through=identity.date_issued,
        notes=notes
        or (
            f"Full annual Title 37 acquisition for {identity.package_id} from "
            f"GovInfo fixture {path.name}; official-base package pin (not eCFR). "
            f"Present granules={len(section_texts)}; gaps={len(gaps)}."
        ),
    )
    if require_full_catalog:
        manifest.assert_full_catalog_coverage()
    validate_manifest(manifest, require_full_catalog=require_full_catalog)

    # Dual-identity safety: eCFR presentation must not equal official package.
    if not acquisition.identities_remain_separate():
        raise EcfrOnlyAcquisitionError(
            "eCFR presentation digest collides with official annual package "
            "digest; refusing acquisition"
        )

    package_meta: dict[str, Any] = {
        "package_id": identity.package_id,
        "year": identity.year,
        "title": identity.title,
        "provider": identity.provider,
        "authority_tier": identity.authority_tier,
        "package_digest_sha256": package_digest,
        "package_root_cid": package_cid,
        "source_url": binding.source_url,
        "fixture_path": str(path),
        "source_kind": "govinfo-annual-fixture",
        "ecfr_presentation_sha256": acquisition.ecfr_presentation_sha256,
        "section_granules_present": sorted(section_texts.keys()),
    }

    out_path = Path(output_dir) if output_dir is not None else None
    receipt = _build_receipt(
        manifest=manifest,
        source_kind="govinfo-annual-fixture",
        fixture_path=path,
        output_dir=out_path if stage else None,
        present_with_text=len(section_texts),
        gap_count=len(gaps),
        notes=manifest.notes,
    )

    if stage:
        if out_path is None:
            raise CfrTitle37AcquireError("--output-dir is required when staging")
        _stage_outputs(
            output_dir=out_path,
            manifest=manifest,
            receipt=receipt,
            section_texts=section_texts,
            package_meta=package_meta,
        )

    return CfrTitle37AcquisitionResult(
        manifest=manifest,
        receipt=receipt,
        section_texts=section_texts,
        source_kind="govinfo-annual-fixture",
        fixture_path=path,
        output_dir=out_path if stage else None,
        package_meta=package_meta,
    )


def acquire_from_ecfr_only_payload(
    payload: Mapping[str, Any],
) -> CfrTitle37AcquisitionResult:
    """Explicit fail-closed path: eCFR-only never completes this task."""

    assert_not_ecfr_only(payload, source_kind="ecfr-only")
    raise EcfrOnlyAcquisitionError(
        "eCFR-only acquisition cannot complete PATLAW-181"
    )


def acquire_cfr_title37_full(
    *,
    year: Any | None = None,
    fixture_path: PathLike | None = None,
    output_dir: PathLike | None = None,
    stage: bool = False,
    mode: MaterializationMode | str = MaterializationMode.ACQUIRE,
    live: bool = False,
    require_full_catalog: bool = True,
    notes: str = "",
    ecfr_only: bool = False,
    max_volumes: int = DEFAULT_LIVE_MAX_VOLUMES,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    delay_seconds: float = DEFAULT_LIVE_VOLUME_DELAY_SECONDS,
    http_get: HttpGetter | None = None,
) -> CfrTitle37AcquisitionResult:
    """Acquire the full annual CFR Title 37 package for a pinned edition.

    Parameters
    ----------
    year:
        Optional calendar year pin. When omitted, year comes from the fixture
        or live package identity.
    fixture_path:
        Official annual GovInfo fixture recipe (default: repo CI fixture).
    output_dir / stage:
        When ``stage`` is true, write manifest, receipt, package meta, and
        section text files under ``output_dir``.
    live:
        Opt-in live GovInfo path. Offline environments fail closed.
    ecfr_only:
        When true, immediately reject (documents the fail-closed contract).
    """

    if ecfr_only:
        raise EcfrOnlyAcquisitionError(
            "eCFR-only / eCFR-partial crawls do not complete annual CFR Title 37 "
            "acquisition (PATLAW-181)"
        )

    if live:
        if year is None or not str(year).strip():
            raise MissingEditionIdentityError(
                "live GovInfo acquisition requires an explicit --year pin "
                "(never 'latest')"
            )
        return acquire_from_govinfo_live(
            year=year,
            mode=mode,
            output_dir=output_dir,
            stage=stage,
            require_full_catalog=require_full_catalog,
            notes=notes,
            max_volumes=max_volumes,
            timeout=timeout,
            delay_seconds=delay_seconds,
            http_get=http_get,
        )

    result = acquire_from_govinfo_fixture(
        fixture_path,
        mode=mode,
        output_dir=output_dir,
        stage=stage,
        require_full_catalog=require_full_catalog,
        notes=notes,
    )

    if year is not None and str(year).strip():
        # Reject unpinned latest; require fixture year match when year requested.
        requested = EditionIdentity.for_year(year)
        if result.manifest.edition_identity.year != requested.year:
            raise MissingEditionIdentityError(
                f"requested year {requested.year!r} does not match fixture "
                f"package year {result.manifest.edition_identity.year!r} "
                f"({result.manifest.edition_identity.package_id})"
            )
        # Ensure package_id form is consistent.
        expected_pid = govinfo_cfr_package_id(
            year=requested.year, title=DEFAULT_TITLE
        )
        if result.package_id != expected_pid:
            raise MissingEditionIdentityError(
                f"package_id {result.package_id!r} does not match {expected_pid!r}"
            )

    return result


def load_and_validate_manifest(
    path: PathLike,
    *,
    require_full_catalog: bool = True,
) -> CfrTitle37FullManifest:
    """Load a staged inventory manifest and validate full-catalog contracts."""

    payload = _load_json_object(Path(path))
    return validate_manifest(payload, require_full_catalog=require_full_catalog)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire full annual CFR Title 37 text package "
            f"({ACQUIRE_TASK_ID}). Offline fixture default; no Hub upload. "
            "eCFR-only crawls are rejected."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help=(
            "Use the repository bounded official annual Title 37 GovInfo "
            "fixture and enumerate the full catalog inventory"
        ),
    )
    input_group.add_argument(
        "--fixture",
        type=Path,
        help="Path to an official annual GovInfo Title 37 fixture recipe JSON",
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing full Title 37 inventory manifest",
    )
    input_group.add_argument(
        "--reject-ecfr-only",
        action="store_true",
        help=(
            "Demonstrate fail-closed rejection of eCFR-only completion "
            "(exits non-zero)"
        ),
    )

    parser.add_argument(
        "--year",
        default=None,
        help=(
            "Pinned calendar year (required with --live; must match fixture "
            "package year when offline)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local staging directory (required with --stage)",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help=(
            "Write manifest, acquisition receipt, package meta, and section "
            "texts under --output-dir. Default is dry-run (in-memory only)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in MaterializationMode],
        default=MaterializationMode.ACQUIRE.value,
        help="Materialization mode recorded on the inventory manifest",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Download official annual Title 37 volume XML from GovInfo "
            "(requires --year; CI stays on fixtures)"
        ),
    )
    parser.add_argument(
        "--live-max-volumes",
        type=int,
        default=DEFAULT_LIVE_MAX_VOLUMES,
        help=(
            "Maximum annual volume packages to probe under --live "
            f"(default {DEFAULT_LIVE_MAX_VOLUMES})"
        ),
    )
    parser.add_argument(
        "--live-timeout-seconds",
        type=float,
        default=DEFAULT_HTTP_TIMEOUT_SECONDS,
        help="HTTP timeout per volume download under --live",
    )
    parser.add_argument(
        "--live-delay-seconds",
        type=float,
        default=DEFAULT_LIVE_VOLUME_DELAY_SECONDS,
        help="Polite delay between live volume downloads",
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the full inventory manifest JSON to stdout",
    )
    parser.add_argument(
        "--print-receipt",
        action="store_true",
        help="Print the acquisition receipt JSON to stdout",
    )
    parser.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress the human-readable summary",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional free-form notes recorded on the manifest/receipt",
    )
    return parser


def _print_summary(result: CfrTitle37AcquisitionResult) -> None:
    manifest = result.manifest
    counts = manifest.counts
    assert counts is not None
    print(f"task_id:                 {ACQUIRE_TASK_ID}")
    print(f"goal_id:                 {ACQUIRE_GOAL_ID}")
    print(f"inventory_task_id:       {INVENTORY_TASK_ID}")
    print(f"schema_version:          {INVENTORY_SCHEMA_VERSION}")
    print(f"acquire_schema_version:  {ACQUIRE_SCHEMA_VERSION}")
    print(f"mode:                    {manifest.mode.value}")
    print(f"source_kind:             {result.source_kind}")
    print(f"package_id:              {result.package_id}")
    print(f"year:                    {manifest.edition_identity.year}")
    print(f"authority_tier:          {manifest.edition_identity.authority_tier}")
    print(f"package_digest_sha256:   {result.package_digest_sha256}")
    print(f"package_root_cid:        {result.package_root_cid}")
    print(f"inventory_digest_sha256: {manifest.inventory_digest_sha256}")
    print(f"manifest_digest_sha256:  {manifest.content_digest()}")
    print(f"total_sections:          {counts.total_sections}")
    print(f"total_parts:             {counts.total_parts}")
    print(f"present_sections:        {counts.present_sections}")
    print(f"gap_sections:            {counts.gap_sections}")
    print(f"present_with_text:       {len(result.section_texts)}")
    print(f"full_catalog:            true")
    print(f"ecfr_only_rejected:      true")
    print(f"hub_upload:              false")
    if result.fixture_path is not None:
        print(f"fixture_path:            {result.fixture_path}")
    if result.output_dir is not None:
        print(f"output_dir:              {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {PACKAGE_META_FILENAME}")
        print(f"  - {SECTIONS_DIRNAME}/...")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.reject_ecfr_only:
        try:
            acquire_cfr_title37_full(ecfr_only=True)
        except EcfrOnlyAcquisitionError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("ecfr_only_rejected: true")
            return 2
        print("ERROR: eCFR-only path did not fail closed", file=sys.stderr)
        return 3

    if args.validate_manifest is not None:
        try:
            manifest = load_and_validate_manifest(args.validate_manifest)
        except (
            CfrTitle37FullError,
            CfrTitle37AcquireError,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        counts = manifest.counts
        assert counts is not None
        print("manifest_ok: true")
        print(f"package_id: {manifest.edition_identity.package_id}")
        print(
            f"package_digest_sha256: "
            f"{manifest.package_binding.package_digest_sha256}"
        )
        print(f"package_root_cid: {manifest.package_binding.package_root_cid}")
        print(f"total_sections: {counts.total_sections}")
        print(f"present_sections: {counts.present_sections}")
        print(f"gap_sections: {counts.gap_sections}")
        print(f"inventory_digest_sha256: {manifest.inventory_digest_sha256}")
        return 0

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required when --stage is set")

    if args.live:
        if not args.year:
            parser.error("--live requires --year YYYY (never 'latest')")
        if args.default_fixture or args.fixture is not None:
            # Live path ignores fixtures; fail loud so operators do not mix modes.
            parser.error("--live is mutually exclusive with --default-fixture/--fixture")
        try:
            result = acquire_from_govinfo_live(
                year=args.year,
                mode=args.mode,
                output_dir=args.output_dir,
                stage=bool(args.stage),
                require_full_catalog=True,
                notes=args.notes or "",
                max_volumes=int(args.live_max_volumes),
                timeout=float(args.live_timeout_seconds),
                delay_seconds=float(args.live_delay_seconds),
            )
        except LiveAcquisitionUnavailableError as exc:
            print(f"ERROR: live acquisition unavailable: {exc}", file=sys.stderr)
            return 2
        except UnpinnedLatestError as exc:
            print(f"ERROR: unpinned latest rejected: {exc}", file=sys.stderr)
            return 2
        except (
            CfrTitle37FullError,
            CfrTitle37AcquireError,
            FileNotFoundError,
            ValueError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    else:
        if not args.default_fixture and args.fixture is None:
            parser.error(
                "one of --default-fixture / --fixture / --live / "
                "--validate-manifest / --reject-ecfr-only is required"
            )
        fixture: Path | None
        if args.default_fixture:
            fixture = default_fixture_path()
        else:
            fixture = args.fixture

        try:
            result = acquire_cfr_title37_full(
                year=args.year,
                fixture_path=fixture,
                output_dir=args.output_dir,
                stage=bool(args.stage),
                mode=args.mode,
                live=False,
                notes=args.notes or "",
            )
        except EcfrOnlyAcquisitionError as exc:
            print(f"ERROR: eCFR-only rejected: {exc}", file=sys.stderr)
            return 2
        except UnpinnedLatestError as exc:
            print(f"ERROR: unpinned latest rejected: {exc}", file=sys.stderr)
            return 2
        except (
            CfrTitle37FullError,
            CfrTitle37AcquireError,
            MissingPackageError,
            FileNotFoundError,
            ValueError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if not args.no_print_summary:
        _print_summary(result)

    if args.print_receipt:
        print(json.dumps(dict(result.receipt), indent=2, sort_keys=True))

    if args.print_manifest:
        print(json.dumps(result.manifest.to_dict(), indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
