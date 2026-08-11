"""Full MPEP section inventory and edition pin contracts (PATLAW-182 / PATLAW-G216).

Defines the serialization and validation boundary for a **pinned** MPEP
edition/revision inventory that enumerates **section-level** (and optional
form-paragraph) anchors across **all** MPEP chapters — not chapter landing
pages alone.

Design invariants
-----------------
* Edition identity requires concrete ``edition`` **and** ``revision`` pins;
  the hard-coded token ``\"latest\"`` is always rejected.
* A complete inventory must cover every required MPEP chapter with at least
  one **section-level** anchor (or an explicit gap for that chapter).
  Chapter-only inventories fail closed.
* Every inventory record and supersession edge is guidance-tier and
  non-binding. Guidance never elevates to statute, regulation, or other
  binding law.
* Content digests (SHA-256) and optional CIDs bind inventory payloads for
  content-addressed acquisition (PATLAW-183).
* No network I/O; this module is pure contracts and offline validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Iterator, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    reject_hard_coded_latest,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.mpep_full.v1"
INTERFACE: Final = "MpepFullSectionInventory@1"
PRODUCER: Final = "producer:mpep-full-section-inventory"
CONFIG_ID: Final = "config:mpep-full-section/v1"
TASK_ID: Final = "PATLAW-182"
GOAL_ID: Final = "PATLAW-G216"
CODE_VERSION: Final = "1.0.0"

MANIFEST_FILENAME: Final = "mpep-full.manifest.json"
MANIFEST_SCHEMA_FILENAME: Final = "mpep_full.manifest.schema.json"

AUTHORITY_TIER_GUIDANCE: Final = AuthorityTier.GUIDANCE.value  # "guidance"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_SECTION_ANCHOR_RE = re.compile(
    r"^(?P<section>\d{2,4}(?:\.\d+)*(?:\([a-z0-9]+\))*)$",
    re.IGNORECASE,
)
_FORM_PARAGRAPH_RE = re.compile(
    r"^(?P<fp>\d+(?:\.\d+)+)$",
)
_CHAPTER_ID_RE = re.compile(r"^(?:\d{3,4}|appx-[A-Za-z0-9]+|index)$", re.IGNORECASE)
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_NONEMPTY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")

# ---------------------------------------------------------------------------
# Required MPEP chapter catalog (Ninth Edition structure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MpepChapterSpec:
    """Static catalog entry for one required MPEP chapter."""

    chapter_id: str
    title: str


# Numbered chapters 100–2900 plus appendices that appear in the official TOC.
# Section anchors (not chapter landings) must be present for every required
# chapter in a complete inventory.
REQUIRED_MPEP_CHAPTERS: Final[tuple[MpepChapterSpec, ...]] = (
    MpepChapterSpec("100", "Secrecy, Access, National Security, and Foreign Filing"),
    MpepChapterSpec("200", "Types, Cross-Noting, and Status of Application"),
    MpepChapterSpec("300", "Ownership and Assignment"),
    MpepChapterSpec("400", "Representative of Applicant or Owner"),
    MpepChapterSpec("500", "Receipt and Handling of Mail and Papers"),
    MpepChapterSpec("600", "Parts, Form, and Content of Application"),
    MpepChapterSpec("700", "Examination of Applications"),
    MpepChapterSpec(
        "800",
        "Restriction in Applications Filed Under 35 U.S.C. 111; Double Patenting",
    ),
    MpepChapterSpec("900", "Prior Art, Classification, and Search"),
    MpepChapterSpec("1000", "Matters Decided by Various U.S. Patent and Trademark Office Officials"),
    MpepChapterSpec(
        "1100",
        "Statutory Invention Registration (SIR); Pre-Grant Publication (PGPub) "
        "and Preissuance Submissions",
    ),
    MpepChapterSpec("1200", "Appeal"),
    MpepChapterSpec("1300", "Allowance and Issue"),
    MpepChapterSpec("1400", "Correction of Patents"),
    MpepChapterSpec("1500", "Design Patents"),
    MpepChapterSpec("1600", "Plant Patents"),
    MpepChapterSpec("1700", "Miscellaneous"),
    MpepChapterSpec("1800", "Patent Cooperation Treaty"),
    MpepChapterSpec("1900", "Protest"),
    MpepChapterSpec("2000", "Duty of Disclosure"),
    MpepChapterSpec("2100", "Patentability"),
    MpepChapterSpec(
        "2200", "Citation of Prior Art and Ex Parte Reexamination of Patents"
    ),
    MpepChapterSpec("2300", "Interference and Derivation Proceedings"),
    MpepChapterSpec("2400", "Biotechnology"),
    MpepChapterSpec("2500", "Maintenance Fees"),
    MpepChapterSpec("2600", "Optional Inter Partes Reexamination"),
    MpepChapterSpec("2700", "Patent Terms, Adjustments, and Extensions"),
    MpepChapterSpec("2800", "Supplemental Examination"),
    MpepChapterSpec("2900", "International Design Applications"),
    MpepChapterSpec("appx-L", "Appendix L — Patent Laws"),
    MpepChapterSpec("appx-R", "Appendix R — Patent Rules"),
    MpepChapterSpec("appx-T", "Appendix T — Patent Cooperation Treaty"),
    MpepChapterSpec("appx-AI", "Appendix AI — Administrative Instructions Under the PCT"),
    MpepChapterSpec("appx-P", "Appendix P — Paris Convention"),
    MpepChapterSpec("appx-II", "Appendix II — List of Decisions Cited"),
    MpepChapterSpec("index", "Index"),
)

REQUIRED_CHAPTER_IDS: Final[frozenset[str]] = frozenset(
    c.chapter_id for c in REQUIRED_MPEP_CHAPTERS
)
REQUIRED_CHAPTER_BY_ID: Final[Mapping[str, MpepChapterSpec]] = MappingProxyType(
    {c.chapter_id: c for c in REQUIRED_MPEP_CHAPTERS}
)

# Representative section anchors used by the compact offline fixture so tests
# and dry-runs can prove full chapter coverage without shipping the full manual.
# Values are real MPEP section numbers (or stable appendix anchors), never
# chapter-landing tokens alone.
_FIXTURE_SECTION_BY_CHAPTER: Final[Mapping[str, str]] = MappingProxyType(
    {
        "100": "101",
        "200": "201",
        "300": "301",
        "400": "401",
        "500": "501",
        "600": "601",
        "700": "706.02",
        "800": "803",
        "900": "901",
        "1000": "1001",
        "1100": "1101",
        "1200": "1201",
        "1300": "1301",
        "1400": "1401",
        "1500": "1501",
        "1600": "1601",
        "1700": "1701",
        "1800": "1801",
        "1900": "1901",
        "2000": "2001",
        "2100": "2106",
        "2200": "2201",
        "2300": "2301",
        "2400": "2401",
        "2500": "2501",
        "2600": "2601",
        "2700": "2701",
        "2800": "2801",
        "2900": "2901",
        "appx-L": "35-usc-101",
        "appx-R": "37-cfr-1.56",
        "appx-T": "pct-art-1",
        "appx-AI": "pct-ai-101",
        "appx-P": "paris-art-4",
        "appx-II": "decisions-index",
        "index": "index-main",
    }
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MpepFullSectionError(ValueError):
    """Base error for full MPEP section inventory contract violations."""

    code: str = "mpep_full_section_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class EditionPinError(MpepFullSectionError):
    """Raised when edition/revision pins are missing, empty, or unpinned."""

    code = "edition_pin_error"


class ChapterOnlyInventoryError(MpepFullSectionError):
    """Raised when inventory is chapter-landing only (no section anchors)."""

    code = "chapter_only_inventory"


class IncompleteChapterCoverageError(MpepFullSectionError):
    """Raised when one or more required chapters lack section anchors."""

    code = "incomplete_chapter_coverage"


class BindingElevationError(MpepFullSectionError):
    """Raised when guidance is elevated to binding law."""

    code = "binding_elevation"


class SchemaValidationError(MpepFullSectionError):
    """Raised when a manifest fails structural or schema validation."""

    code = "schema_validation"


class MissingCutoffError(MpepFullSectionError):
    """Raised when a required cutoff date is missing."""

    code = "missing_cutoff"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InventoryEntryKind(str, Enum):
    """Kinds of full-inventory anchors."""

    MPEP_SECTION = "mpep_section"
    FORM_PARAGRAPH = "form_paragraph"
    APPENDIX_ANCHOR = "appendix_anchor"
    INDEX_ANCHOR = "index_anchor"

    @classmethod
    def coerce(cls, value: Any) -> "InventoryEntryKind":
        if isinstance(value, InventoryEntryKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "mpep_section": cls.MPEP_SECTION,
            "section": cls.MPEP_SECTION,
            "mpep": cls.MPEP_SECTION,
            "form_paragraph": cls.FORM_PARAGRAPH,
            "fp": cls.FORM_PARAGRAPH,
            "formparagraph": cls.FORM_PARAGRAPH,
            "appendix_anchor": cls.APPENDIX_ANCHOR,
            "appendix": cls.APPENDIX_ANCHOR,
            "index_anchor": cls.INDEX_ANCHOR,
            "index": cls.INDEX_ANCHOR,
        }
        if text not in aliases:
            raise MpepFullSectionError(f"unsupported inventory entry kind: {value!r}")
        return aliases[text]


class InventoryEntryStatus(str, Enum):
    """Whether section text is present or recorded as an explicit gap."""

    PRESENT = "present"
    GAP = "gap"

    @classmethod
    def coerce(cls, value: Any) -> "InventoryEntryStatus":
        if isinstance(value, InventoryEntryStatus):
            return value
        text = str(value or "").strip().lower()
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise MpepFullSectionError(f"unsupported inventory entry status: {value!r}")


class GapKind(str, Enum):
    """Explicit inventory / acquisition gap kinds."""

    UNAVAILABLE = "unavailable"
    CONTENT_CHANGED = "content_changed"
    DELAYED_INVENTORY = "delayed_inventory"
    HASH_MISMATCH = "hash_mismatch"
    RETRIEVAL_FAILED = "retrieval_failed"
    CHAPTER_LANDING_ONLY = "chapter_landing_only"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GapKind":
        if isinstance(value, GapKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        return cls.OTHER


class SupersessionRelation(str, Enum):
    """How later guidance relates to earlier manual or guidance text."""

    SUPERSEDES = "supersedes"
    PARTIALLY_SUPERSEDES = "partially_supersedes"
    CLARIFIES = "clarifies"
    WITHDRAWS = "withdraws"
    RESTORES = "restores"

    @classmethod
    def coerce(cls, value: Any) -> "SupersessionRelation":
        if isinstance(value, SupersessionRelation):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise MpepFullSectionError(f"unsupported supersession relation: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MpepFullSectionError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise MpepFullSectionError(f"{name} must not contain NUL")
    if len(text) > max_len:
        raise MpepFullSectionError(f"{name} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, name: str = "value", *, max_len: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, max_len=max_len)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MpepFullSectionError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _optional_sha256(value: Any, name: str = "sha256") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_sha256(value, name)


def _optional_cid(value: Any, name: str = "cid") -> Optional[str]:
    text = _optional_str(value, name, max_len=256)
    if text is None:
        return None
    if not _CID_RE.fullmatch(text):
        raise MpepFullSectionError(f"{name} must be a CIDv1 base32 token")
    return text


def _parse_required_date(value: Any, *, name: str = "cutoff") -> date:
    if value is None or value == "":
        raise MissingCutoffError(f"{name} is required on every edition pin / inventory record")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()[:10]
        if not _DATE_RE.fullmatch(text):
            raise MpepFullSectionError(f"{name} must be an ISO date (YYYY-MM-DD)")
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise MpepFullSectionError(f"{name} must be an ISO date") from exc
    raise MpepFullSectionError(f"{name} must be a date or ISO date string")


def _parse_optional_date(value: Any, *, name: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    return _parse_required_date(value, name=name)


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _parse_utc(value: Any, *, name: str = "retrieved_at") -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MpepFullSectionError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise MpepFullSectionError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    normalized = dt.astimezone(timezone.utc).replace(
        microsecond=(dt.microsecond // 1000) * 1000
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def _omit_none(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` (JSON Schema optional fields)."""
    return {k: v for k, v in payload.items() if v is not None}


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for contract round-trip equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def cid_from_digest(digest: str, *, prefix: str = "baguqeera") -> str:
    """Deterministic CIDv1 (base32) derived from a SHA-256 hex digest.

    Uses the shared IR identity helper so tokens match ``^b[a-z2-7]{20,}$``.
    The *prefix* argument is retained for call-site compatibility and ignored;
    identity is fully determined by the digest bytes.
    """
    del prefix  # retained for API compatibility with other patent contracts
    text = _require_sha256(digest, "digest")
    return cid_v1_from_digest(bytes.fromhex(text))


def default_manifest_schema_path() -> Path:
    """Return the on-disk path to ``mpep_full.manifest.schema.json``."""
    # .../ipfs_datasets_py/processors/domains/patent/this_file.py → repo root
    repo_root = Path(__file__).resolve().parents[4]
    return (
        repo_root
        / "data"
        / "release"
        / "patent_legal_intelligence"
        / MANIFEST_SCHEMA_FILENAME
    )


def load_manifest_schema(*, path: PathLike | None = None) -> dict[str, Any]:
    """Load the release JSON Schema for the full MPEP inventory manifest."""
    schema_path = Path(path) if path is not None else default_manifest_schema_path()
    if not schema_path.is_file():
        raise SchemaValidationError(f"manifest schema not found: {schema_path}")
    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SchemaValidationError("manifest schema root must be an object")
    return raw


# ---------------------------------------------------------------------------
# Edition pin / section / chapter identity
# ---------------------------------------------------------------------------


def parse_mpep_edition_revision(
    *,
    edition: Any,
    revision: Any,
) -> tuple[str, str]:
    """Validate concrete MPEP edition + revision (never ``latest``)."""
    if edition is None or (isinstance(edition, str) and not edition.strip()):
        raise EditionPinError("edition pin is required (concrete edition, never 'latest')")
    if revision is None or (isinstance(revision, str) and not revision.strip()):
        raise EditionPinError("revision pin is required (concrete revision, never 'latest')")
    edition_s = _require_non_empty_str(str(edition), "edition", max_len=64)
    revision_s = _require_non_empty_str(str(revision), "revision", max_len=64)
    try:
        reject_hard_coded_latest(edition_s, field_name="edition")
        reject_hard_coded_latest(revision_s, field_name="revision")
    except HardCodedLatestEditionError as exc:
        raise EditionPinError(str(exc)) from exc
    if _LATEST_TOKEN_RE.fullmatch(edition_s) or _LATEST_TOKEN_RE.fullmatch(revision_s):
        raise EditionPinError("edition/revision must not be the hard-coded token 'latest'")
    return edition_s, revision_s


def normalize_mpep_section(section: Any) -> str:
    """Normalize an MPEP section token (e.g. ``2106``, ``§ 2106.04(a)``)."""
    if section is None:
        raise MpepFullSectionError("section must be non-empty")
    text = str(section).strip()
    if not text:
        raise MpepFullSectionError("section must be non-empty")
    # Strip common prefixes.
    text = re.sub(r"^(?:mpep\s*)?(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?", "", text, flags=re.I)
    text = re.sub(r"\s+", "", text)
    text = text.lstrip("§").strip()
    if text.endswith(".") and text.count(".") == 1 and not re.search(r"\d\.\d", text):
        text = text[:-1]
    match = _SECTION_ANCHOR_RE.fullmatch(text)
    if not match:
        # Allow non-numeric appendix/index anchors through a looser path.
        cleaned = text.lower().replace(" ", "-")
        if not cleaned or len(cleaned) > 128:
            raise MpepFullSectionError(f"unrecognized MPEP section token: {section!r}")
        return cleaned
    return match.group("section")


def normalize_form_paragraph(token: Any) -> str:
    """Normalize a form-paragraph id (e.g. ``7.05``, ``FP 7.05``)."""
    if token is None:
        raise MpepFullSectionError("form_paragraph must be non-empty")
    text = str(token).strip()
    if not text:
        raise MpepFullSectionError("form_paragraph must be non-empty")
    match = re.search(
        r"(?:fp|form\s*paragraph|¶)\s*[#:]?\s*(?P<fp>[\d.]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group("fp").strip()
    cleaned = text.lstrip("#¶").strip()
    cleaned = re.sub(r"^(?:fp|form\s*paragraph)\s*[#:]?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    if not cleaned or not _FORM_PARAGRAPH_RE.fullmatch(cleaned):
        raise MpepFullSectionError(f"unrecognized form paragraph token: {token!r}")
    return cleaned


def normalize_chapter_id(chapter: Any) -> str:
    """Normalize a chapter id (``700``, ``appx-L``, ``index``)."""
    text = _require_non_empty_str(str(chapter), "chapter_id", max_len=32)
    text = text.strip()
    lower = text.lower()
    if lower in {"index", "idx"}:
        return "index"
    if lower.startswith("appx") or lower.startswith("appendix"):
        # appx-L / appendix-L / Appendix L
        tail = re.sub(r"^(?:appx|appendix)[-\s_]*", "", text, flags=re.I)
        tail = tail.strip().upper().replace(" ", "")
        if not tail:
            raise MpepFullSectionError(f"unrecognized appendix chapter: {chapter!r}")
        return f"appx-{tail}"
    # Numeric chapter: strip leading zeros style but keep 100/1000 distinct.
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        raise MpepFullSectionError(f"unrecognized chapter id: {chapter!r}")
    return digits


def chapter_id_for_section(section: Any) -> str:
    """Infer the parent MPEP chapter id from a normalized section token."""
    sec = normalize_mpep_section(section)
    if sec.startswith("35-usc") or sec.startswith("35usc"):
        return "appx-L"
    if sec.startswith("37-cfr") or sec.startswith("37cfr"):
        return "appx-R"
    if sec.startswith("pct-art") or sec.startswith("pct-ai"):
        return "appx-AI" if "ai" in sec else "appx-T"
    if sec.startswith("paris"):
        return "appx-P"
    if sec.startswith("decision") or sec == "decisions-index":
        return "appx-II"
    if sec.startswith("index"):
        return "index"
    m = re.match(r"^(\d+)", sec)
    if not m:
        raise MpepFullSectionError(f"cannot infer chapter for section {section!r}")
    digits = m.group(1)
    if len(digits) <= 3:
        # 101 → 100, 706 → 700
        return f"{digits[0]}00"
    # 1001 → 1000, 2106 → 2100
    return f"{digits[:2]}00"


def is_chapter_landing_anchor(*, chapter_id: str, section_anchor: str) -> bool:
    """Return True when *section_anchor* is only the chapter landing token.

    Chapter landings (e.g. ``700`` for chapter 700, or ``chapter-2100``) are
    insufficient alone for full-section inventory acceptance.
    """
    ch = normalize_chapter_id(chapter_id)
    sec = str(section_anchor or "").strip().lower()
    if not sec:
        return True
    if sec in {ch.lower(), f"chapter-{ch.lower()}", f"ch{ch.lower()}", f"mpep-{ch.lower()}"}:
        return True
    # Zero-padded chapter forms: "0700" for chapter 700
    if ch.isdigit() and sec.isdigit() and int(sec) == int(ch):
        return True
    return False


def is_section_level_anchor(
    *,
    chapter_id: str,
    section_anchor: str,
    kind: InventoryEntryKind | str,
) -> bool:
    """Return True when the anchor is a true section/form-paragraph level pin."""
    kind_v = InventoryEntryKind.coerce(kind)
    if kind_v is InventoryEntryKind.FORM_PARAGRAPH:
        try:
            normalize_form_paragraph(section_anchor)
            return True
        except MpepFullSectionError:
            return False
    if kind_v in (InventoryEntryKind.APPENDIX_ANCHOR, InventoryEntryKind.INDEX_ANCHOR):
        return not is_chapter_landing_anchor(
            chapter_id=chapter_id, section_anchor=section_anchor
        )
    if is_chapter_landing_anchor(chapter_id=chapter_id, section_anchor=section_anchor):
        return False
    try:
        normalize_mpep_section(section_anchor)
    except MpepFullSectionError:
        return False
    return True


def assert_guidance_not_elevated(
    *,
    authority_tier: Any = AUTHORITY_TIER_GUIDANCE,
    is_binding: Any = False,
    elevates_to_law: Any = False,
    label: str = "record",
) -> None:
    """Fail closed when a record attempts to elevate guidance to binding law."""
    tier_text = str(authority_tier or "").strip().lower().replace("_", "-")
    if tier_text and tier_text not in {
        AUTHORITY_TIER_GUIDANCE,
        "guidance",
    }:
        raise BindingElevationError(
            f"{label}: authority_tier must be 'guidance' (got {authority_tier!r}); "
            "MPEP inventory never elevates to binding law"
        )
    if is_binding is True or str(is_binding).strip().lower() in {"true", "1", "yes"}:
        raise BindingElevationError(
            f"{label}: is_binding must be false; guidance never elevates to binding law"
        )
    if elevates_to_law is True or str(elevates_to_law).strip().lower() in {
        "true",
        "1",
        "yes",
    }:
        raise BindingElevationError(
            f"{label}: elevates_to_law must be false; guidance supersession "
            "never elevates either side to law"
        )


def stable_section_identity(
    *,
    kind: InventoryEntryKind | str,
    anchor: Any,
    jurisdiction: str = "US",
) -> str:
    """Stable identity independent of packaging format.

    Shape: ``mpep:{jurisdiction}:{kind}:{anchor}``
    """
    kind_v = InventoryEntryKind.coerce(kind)
    if kind_v is InventoryEntryKind.FORM_PARAGRAPH:
        token = normalize_form_paragraph(anchor)
    else:
        token = normalize_mpep_section(anchor)
    jur = _require_non_empty_str(jurisdiction, "jurisdiction").lower()
    return f"mpep:{jur}:{kind_v.value}:{token}"


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MpepEditionPin:
    """Concrete MPEP edition + revision identity with cutoff date.

    Both ``edition`` and ``revision`` are required. The unpinned token
    ``\"latest\"`` is always rejected.
    """

    edition: str
    revision: str
    cutoff: date
    provider: str = "uspto"
    publication_date: Optional[date] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        edition_s, revision_s = parse_mpep_edition_revision(
            edition=self.edition, revision=self.revision
        )
        object.__setattr__(self, "edition", edition_s)
        object.__setattr__(self, "revision", revision_s)
        object.__setattr__(self, "cutoff", _parse_required_date(self.cutoff, name="cutoff"))
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider", max_len=64)
        )
        if self.publication_date is not None:
            object.__setattr__(
                self,
                "publication_date",
                _parse_required_date(self.publication_date, name="publication_date"),
            )
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_non_empty_str(self.source_url, "source_url", max_len=2048),
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes", max_len=4096)
            )
        if not isinstance(self.metadata, Mapping):
            raise MpepFullSectionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def edition_key(self) -> str:
        """Stable edition/revision identity token (never ``latest``)."""
        return f"mpep-{self.edition}-r{self.revision}"

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "content_sha256": self.content_sha256,
                "cutoff": _date_to_str(self.cutoff),
                "edition": self.edition,
                "edition_key": self.edition_key,
                "metadata": _deep_sorted(self.metadata) or None,
                "notes": self.notes,
                "provider": self.provider,
                "publication_date": _date_to_str(self.publication_date),
                "retrieved_at": _format_utc(self.retrieved_at),
                "revision": self.revision,
                "source_url": self.source_url,
            }
        )


    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepEditionPin":
        if not isinstance(value, Mapping):
            raise EditionPinError("edition pin must be a mapping")
        if value.get("cutoff") in (None, ""):
            raise MissingCutoffError("cutoff is required on every edition pin")
        # Fail closed if either pin is absent before parse.
        if value.get("edition") in (None, "") and value.get("edition_key") in (None, ""):
            raise EditionPinError("edition pin is required")
        if value.get("revision") in (None, ""):
            raise EditionPinError("revision pin is required")
        edition_raw = value.get("edition") or ""
        if not edition_raw and value.get("edition_key"):
            # Parse "mpep-9-r07.2022" → edition 9 when only edition_key supplied
            # still requires revision field separately.
            edition_raw = str(value.get("edition_key"))
        return cls(
            edition=str(edition_raw),
            revision=str(value.get("revision") or ""),
            cutoff=value["cutoff"],
            provider=str(value.get("provider") or "uspto"),
            publication_date=value.get("publication_date"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MpepSectionInventoryEntry:
    """One section / form-paragraph / appendix anchor in the full inventory.

    Always guidance-tier and non-binding. Chapter-landing-only anchors are
    rejected for ``mpep_section`` entries that claim status ``present``.
    """

    entry_id: str
    chapter_id: str
    section_anchor: str
    kind: InventoryEntryKind = InventoryEntryKind.MPEP_SECTION
    status: InventoryEntryStatus = InventoryEntryStatus.PRESENT
    title: Optional[str] = None
    citation: Optional[str] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    content_cid: Optional[str] = None
    media_type: Optional[str] = None
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    gap_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_id", _require_non_empty_str(self.entry_id, "entry_id", max_len=256)
        )
        if not _NONEMPTY_ID_RE.fullmatch(self.entry_id):
            raise MpepFullSectionError(f"entry_id is not a valid identifier: {self.entry_id!r}")
        ch = normalize_chapter_id(self.chapter_id)
        object.__setattr__(self, "chapter_id", ch)
        kind_v = InventoryEntryKind.coerce(self.kind)
        object.__setattr__(self, "kind", kind_v)
        status_v = InventoryEntryStatus.coerce(self.status)
        object.__setattr__(self, "status", status_v)

        if kind_v is InventoryEntryKind.FORM_PARAGRAPH:
            anchor = normalize_form_paragraph(self.section_anchor)
        else:
            anchor = normalize_mpep_section(self.section_anchor)
        object.__setattr__(self, "section_anchor", anchor)

        # Section-level requirement: present mpep_section entries must not be
        # chapter landings. Gap entries may record a chapter-landing shortfall.
        if (
            status_v is InventoryEntryStatus.PRESENT
            and kind_v is InventoryEntryKind.MPEP_SECTION
            and is_chapter_landing_anchor(chapter_id=ch, section_anchor=anchor)
        ):
            raise ChapterOnlyInventoryError(
                f"entry {self.entry_id!r}: present mpep_section inventory must use "
                f"a section-level anchor, not chapter landing {anchor!r}"
            )

        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label=f"entry {self.entry_id}",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)

        if self.title is not None:
            object.__setattr__(
                self, "title", _require_non_empty_str(self.title, "title", max_len=512)
            )
        if self.citation is not None:
            object.__setattr__(
                self,
                "citation",
                _require_non_empty_str(self.citation, "citation", max_len=256),
            )
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_non_empty_str(self.source_url, "source_url", max_len=2048),
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        if self.content_cid is not None:
            object.__setattr__(
                self, "content_cid", _optional_cid(self.content_cid, "content_cid")
            )
        if self.media_type is not None:
            object.__setattr__(
                self,
                "media_type",
                _require_non_empty_str(self.media_type, "media_type", max_len=128),
            )
        if status_v is InventoryEntryStatus.GAP:
            if not self.gap_reason:
                raise MpepFullSectionError(
                    f"entry {self.entry_id!r}: gap status requires gap_reason"
                )
            object.__setattr__(
                self,
                "gap_reason",
                _require_non_empty_str(self.gap_reason, "gap_reason", max_len=2048),
            )
        elif self.gap_reason is not None:
            object.__setattr__(
                self,
                "gap_reason",
                _require_non_empty_str(self.gap_reason, "gap_reason", max_len=2048),
            )
        if not isinstance(self.metadata, Mapping):
            raise MpepFullSectionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_section_level(self) -> bool:
        return is_section_level_anchor(
            chapter_id=self.chapter_id,
            section_anchor=self.section_anchor,
            kind=self.kind,
        )

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "chapter_id": self.chapter_id,
                "citation": self.citation,
                "content_cid": self.content_cid,
                "content_sha256": self.content_sha256,
                "entry_id": self.entry_id,
                "gap_reason": self.gap_reason,
                "is_binding": False,
                "kind": self.kind.value,
                "media_type": self.media_type,
                "metadata": _deep_sorted(self.metadata) or None,
                "section_anchor": self.section_anchor,
                "source_url": self.source_url,
                "status": self.status.value,
                "title": self.title,
            }
        )


    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepSectionInventoryEntry":
        if not isinstance(value, Mapping):
            raise MpepFullSectionError("inventory entry must be a mapping")
        return cls(
            entry_id=str(value.get("entry_id") or value.get("id") or ""),
            chapter_id=str(value.get("chapter_id") or value.get("chapter") or ""),
            section_anchor=str(
                value.get("section_anchor")
                or value.get("section")
                or value.get("anchor")
                or ""
            ),
            kind=InventoryEntryKind.coerce(
                value.get("kind", InventoryEntryKind.MPEP_SECTION)
            ),
            status=InventoryEntryStatus.coerce(
                value.get("status", InventoryEntryStatus.PRESENT)
            ),
            title=value.get("title"),
            citation=value.get("citation"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            content_cid=value.get("content_cid"),
            media_type=value.get("media_type"),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            gap_reason=value.get("gap_reason"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MpepInventoryGap:
    """Explicit gap when a section or chapter inventory unit is incomplete."""

    gap_id: str
    kind: GapKind
    chapter_id: str
    reason: str
    section_anchor: Optional[str] = None
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    expected_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    source_url: Optional[str] = None
    detected_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "gap_id", _require_non_empty_str(self.gap_id, "gap_id", max_len=256)
        )
        object.__setattr__(self, "kind", GapKind.coerce(self.kind))
        object.__setattr__(self, "chapter_id", normalize_chapter_id(self.chapter_id))
        object.__setattr__(
            self, "reason", _require_non_empty_str(self.reason, "reason", max_len=2048)
        )
        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=False,
            elevates_to_law=False,
            label=f"gap {self.gap_id}",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        if self.section_anchor is not None:
            object.__setattr__(
                self,
                "section_anchor",
                normalize_mpep_section(self.section_anchor)
                if self.kind is not GapKind.CHAPTER_LANDING_ONLY
                else _require_non_empty_str(str(self.section_anchor), "section_anchor"),
            )
        if self.expected_sha256 is not None:
            object.__setattr__(
                self,
                "expected_sha256",
                _require_sha256(self.expected_sha256, "expected_sha256"),
            )
        if self.observed_sha256 is not None:
            object.__setattr__(
                self,
                "observed_sha256",
                _require_sha256(self.observed_sha256, "observed_sha256"),
            )
        if self.source_url is not None:
            object.__setattr__(
                self,
                "source_url",
                _require_non_empty_str(self.source_url, "source_url", max_len=2048),
            )
        if self.detected_at is not None:
            object.__setattr__(
                self, "detected_at", _parse_utc(self.detected_at, name="detected_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise MpepFullSectionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "chapter_id": self.chapter_id,
                "detected_at": _format_utc(self.detected_at),
                "expected_sha256": self.expected_sha256,
                "gap_id": self.gap_id,
                "kind": self.kind.value,
                "metadata": _deep_sorted(self.metadata) or None,
                "observed_sha256": self.observed_sha256,
                "reason": self.reason,
                "section_anchor": self.section_anchor,
                "source_url": self.source_url,
            }
        )


    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepInventoryGap":
        if not isinstance(value, Mapping):
            raise MpepFullSectionError("gap must be a mapping")
        return cls(
            gap_id=str(value.get("gap_id") or ""),
            kind=GapKind.coerce(value.get("kind", GapKind.OTHER)),
            chapter_id=str(value.get("chapter_id") or ""),
            reason=str(value.get("reason") or ""),
            section_anchor=value.get("section_anchor"),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            expected_sha256=value.get("expected_sha256"),
            observed_sha256=value.get("observed_sha256"),
            source_url=value.get("source_url"),
            detected_at=value.get("detected_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MpepSupersessionRecord:
    """Later guidance superseding earlier manual/guidance text.

    Both endpoints remain guidance-tier. The edge never elevates either side
    to statute, regulation, or other binding law.
    """

    successor_id: str
    predecessor_id: str
    relation: SupersessionRelation = SupersessionRelation.SUPERSEDES
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    remains_guidance: bool = True
    elevates_to_law: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "successor_id",
            _require_non_empty_str(self.successor_id, "successor_id", max_len=256),
        )
        object.__setattr__(
            self,
            "predecessor_id",
            _require_non_empty_str(self.predecessor_id, "predecessor_id", max_len=256),
        )
        object.__setattr__(self, "relation", SupersessionRelation.coerce(self.relation))
        if self.effective_date is not None:
            object.__setattr__(
                self,
                "effective_date",
                _parse_required_date(self.effective_date, name="effective_date"),
            )
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _require_non_empty_str(self.reason, "reason", max_len=2048)
            )
        if self.elevates_to_law:
            raise BindingElevationError(
                "guidance supersession must not elevate either side to law"
            )
        if not self.remains_guidance:
            raise BindingElevationError(
                "guidance supersession must leave both sides as guidance-tier"
            )
        object.__setattr__(self, "remains_guidance", True)
        object.__setattr__(self, "elevates_to_law", False)
        if not isinstance(self.metadata, Mapping):
            raise MpepFullSectionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "effective_date": _date_to_str(self.effective_date),
                "elevates_to_law": False,
                "metadata": _deep_sorted(self.metadata) or None,
                "predecessor_id": self.predecessor_id,
                "reason": self.reason,
                "relation": self.relation.value,
                "remains_guidance": True,
                "successor_id": self.successor_id,
            }
        )


    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepSupersessionRecord":
        if not isinstance(value, Mapping):
            raise MpepFullSectionError("supersession record must be a mapping")
        return cls(
            successor_id=str(value.get("successor_id") or value.get("later_id") or ""),
            predecessor_id=str(
                value.get("predecessor_id") or value.get("earlier_id") or ""
            ),
            relation=SupersessionRelation.coerce(
                value.get("relation", SupersessionRelation.SUPERSEDES)
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
            remains_guidance=bool(value.get("remains_guidance", True)),
            elevates_to_law=bool(value.get("elevates_to_law", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MpepChapterCoverage:
    """Per-chapter tallies for inventory completeness checks."""

    chapter_id: str
    title: str
    section_count: int
    form_paragraph_count: int = 0
    gap_count: int = 0
    section_level_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "chapter_id", normalize_chapter_id(self.chapter_id))
        object.__setattr__(
            self, "title", _require_non_empty_str(self.title, "title", max_len=512)
        )
        for name in (
            "section_count",
            "form_paragraph_count",
            "gap_count",
            "section_level_count",
        ):
            raw = getattr(self, name)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise MpepFullSectionError(f"{name} must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "form_paragraph_count": self.form_paragraph_count,
            "gap_count": self.gap_count,
            "section_count": self.section_count,
            "section_level_count": self.section_level_count,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepChapterCoverage":
        if not isinstance(value, Mapping):
            raise MpepFullSectionError("chapter coverage must be a mapping")
        return cls(
            chapter_id=str(value.get("chapter_id") or ""),
            title=str(value.get("title") or ""),
            section_count=int(value.get("section_count") or 0),
            form_paragraph_count=int(value.get("form_paragraph_count") or 0),
            gap_count=int(value.get("gap_count") or 0),
            section_level_count=int(value.get("section_level_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class MpepFullInventoryCounts:
    """Aggregate inventory counts bound into the manifest."""

    chapters_required: int
    chapters_covered: int
    section_entries: int
    form_paragraph_entries: int
    gap_entries: int
    section_level_entries: int
    supersession_edges: int = 0

    def __post_init__(self) -> None:
        for name in (
            "chapters_required",
            "chapters_covered",
            "section_entries",
            "form_paragraph_entries",
            "gap_entries",
            "section_level_entries",
            "supersession_edges",
        ):
            raw = getattr(self, name)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise MpepFullSectionError(f"{name} must be a non-negative int")

    def to_dict(self) -> dict[str, int]:
        return {
            "chapters_covered": self.chapters_covered,
            "chapters_required": self.chapters_required,
            "form_paragraph_entries": self.form_paragraph_entries,
            "gap_entries": self.gap_entries,
            "section_entries": self.section_entries,
            "section_level_entries": self.section_level_entries,
            "supersession_edges": self.supersession_edges,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepFullInventoryCounts":
        if not isinstance(value, Mapping):
            raise MpepFullSectionError("counts must be a mapping")
        return cls(
            chapters_required=int(value.get("chapters_required") or 0),
            chapters_covered=int(value.get("chapters_covered") or 0),
            section_entries=int(value.get("section_entries") or 0),
            form_paragraph_entries=int(value.get("form_paragraph_entries") or 0),
            gap_entries=int(value.get("gap_entries") or 0),
            section_level_entries=int(value.get("section_level_entries") or 0),
            supersession_edges=int(value.get("supersession_edges") or 0),
        )


# ---------------------------------------------------------------------------
# Coverage / inventory validation
# ---------------------------------------------------------------------------


def compute_chapter_coverage(
    inventory: Sequence[MpepSectionInventoryEntry],
) -> list[MpepChapterCoverage]:
    """Aggregate per-chapter tallies from inventory entries."""
    by_chapter: dict[str, list[MpepSectionInventoryEntry]] = {
        c.chapter_id: [] for c in REQUIRED_MPEP_CHAPTERS
    }
    for entry in inventory:
        by_chapter.setdefault(entry.chapter_id, []).append(entry)

    out: list[MpepChapterCoverage] = []
    for spec in REQUIRED_MPEP_CHAPTERS:
        entries = by_chapter.get(spec.chapter_id, [])
        section_entries = [
            e for e in entries if e.kind is not InventoryEntryKind.FORM_PARAGRAPH
        ]
        fp_entries = [e for e in entries if e.kind is InventoryEntryKind.FORM_PARAGRAPH]
        gaps = [e for e in entries if e.status is InventoryEntryStatus.GAP]
        section_level = [e for e in entries if e.is_section_level]
        out.append(
            MpepChapterCoverage(
                chapter_id=spec.chapter_id,
                title=spec.title,
                section_count=len(section_entries),
                form_paragraph_count=len(fp_entries),
                gap_count=len(gaps),
                section_level_count=len(section_level),
            )
        )
    return out


def chapters_with_section_level_coverage(
    inventory: Sequence[MpepSectionInventoryEntry],
) -> frozenset[str]:
    """Return chapter ids that have at least one section-level anchor."""
    covered: set[str] = set()
    for entry in inventory:
        if entry.is_section_level:
            covered.add(entry.chapter_id)
    return frozenset(covered)


def validate_full_chapter_coverage(
    inventory: Sequence[MpepSectionInventoryEntry],
    *,
    require_all_chapters: bool = True,
) -> frozenset[str]:
    """Ensure inventory enumerates section anchors across all required chapters.

    Raises:
        ChapterOnlyInventoryError: inventory has no section-level anchors.
        IncompleteChapterCoverageError: one or more required chapters missing.
    """
    if not inventory:
        raise IncompleteChapterCoverageError(
            "inventory must not be empty; enumerate section anchors across all chapters"
        )

    section_level = [e for e in inventory if e.is_section_level]
    if not section_level:
        raise ChapterOnlyInventoryError(
            "inventory is chapter-only: no section-level anchors found; "
            "chapter landing pages cannot satisfy full MPEP inventory acceptance"
        )

    covered = chapters_with_section_level_coverage(inventory)
    if require_all_chapters:
        missing = sorted(REQUIRED_CHAPTER_IDS - covered)
        if missing:
            raise IncompleteChapterCoverageError(
                "inventory missing section-level anchors for chapters: "
                + ", ".join(missing)
            )
    return covered


def validate_inventory_not_chapter_only(
    inventory: Sequence[MpepSectionInventoryEntry],
) -> None:
    """Reject inventories that only list chapter landing pages."""
    if not inventory:
        raise ChapterOnlyInventoryError("empty inventory is not a full section inventory")
    if not any(e.is_section_level for e in inventory):
        raise ChapterOnlyInventoryError(
            "chapter-only inventories cannot satisfy acceptance; "
            "enumerate section anchors (e.g. 706.02), not only chapter landings"
        )
    # Also reject if every chapter's only entries are landings.
    by_ch: dict[str, list[MpepSectionInventoryEntry]] = {}
    for e in inventory:
        by_ch.setdefault(e.chapter_id, []).append(e)
    landing_only_chapters = [
        ch
        for ch, entries in by_ch.items()
        if entries and not any(e.is_section_level for e in entries)
    ]
    # Landing-only chapters are allowed only as interim gaps when other chapters
    # have section coverage; full acceptance still requires all chapters.
    _ = landing_only_chapters


def compute_counts(
    inventory: Sequence[MpepSectionInventoryEntry],
    *,
    supersessions: Sequence[MpepSupersessionRecord] = (),
    gaps: Sequence[MpepInventoryGap] = (),
) -> MpepFullInventoryCounts:
    covered = chapters_with_section_level_coverage(inventory)
    return MpepFullInventoryCounts(
        chapters_required=len(REQUIRED_MPEP_CHAPTERS),
        chapters_covered=len(covered),
        section_entries=sum(
            1 for e in inventory if e.kind is not InventoryEntryKind.FORM_PARAGRAPH
        ),
        form_paragraph_entries=sum(
            1 for e in inventory if e.kind is InventoryEntryKind.FORM_PARAGRAPH
        ),
        gap_entries=sum(1 for e in inventory if e.status is InventoryEntryStatus.GAP)
        + len(gaps),
        section_level_entries=sum(1 for e in inventory if e.is_section_level),
        supersession_edges=len(supersessions),
    )


# ---------------------------------------------------------------------------
# Full inventory manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MpepFullInventoryManifest:
    """Pinned full MPEP section inventory manifest.

    Acceptance:
    * ``edition_pin`` carries concrete edition **and** revision (never latest)
    * ``inventory`` enumerates section anchors across **all** required chapters
    * guidance never elevates to binding law
    """

    edition_pin: MpepEditionPin
    inventory: tuple[MpepSectionInventoryEntry, ...]
    chapter_coverage: tuple[MpepChapterCoverage, ...]
    counts: MpepFullInventoryCounts
    inventory_digest_sha256: str
    package_digest_sha256: str
    package_root_cid: str
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    producer: str = PRODUCER
    config_id: str = CONFIG_ID
    code_version: str = CODE_VERSION
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    supersessions: tuple[MpepSupersessionRecord, ...] = ()
    gaps: tuple[MpepInventoryGap, ...] = ()
    partition: str = "public"
    mode: str = "dry_run"
    staged_at_utc: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edition_pin, MpepEditionPin):
            raise EditionPinError("edition_pin must be an MpepEditionPin")
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        if self.interface != INTERFACE:
            raise SchemaValidationError(
                f"interface must be {INTERFACE!r}, got {self.interface!r}"
            )
        if self.task_id != TASK_ID:
            raise SchemaValidationError(f"task_id must be {TASK_ID!r}")
        if self.goal_id != GOAL_ID:
            raise SchemaValidationError(f"goal_id must be {GOAL_ID!r}")
        object.__setattr__(
            self, "producer", _require_non_empty_str(self.producer, "producer")
        )
        object.__setattr__(
            self, "config_id", _require_non_empty_str(self.config_id, "config_id")
        )
        object.__setattr__(
            self,
            "code_version",
            _require_non_empty_str(self.code_version, "code_version", max_len=64),
        )
        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label="manifest",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)

        inv = tuple(self.inventory)
        if not inv:
            raise IncompleteChapterCoverageError(
                "inventory must enumerate section anchors across all chapters"
            )
        object.__setattr__(self, "inventory", inv)
        validate_inventory_not_chapter_only(inv)
        validate_full_chapter_coverage(inv, require_all_chapters=True)

        object.__setattr__(self, "supersessions", tuple(self.supersessions))
        object.__setattr__(self, "gaps", tuple(self.gaps))
        for edge in self.supersessions:
            if not isinstance(edge, MpepSupersessionRecord):
                raise MpepFullSectionError("supersessions must be MpepSupersessionRecord")
            assert_guidance_not_elevated(
                authority_tier=AUTHORITY_TIER_GUIDANCE,
                is_binding=False,
                elevates_to_law=edge.elevates_to_law,
                label="supersession",
            )

        coverage = tuple(self.chapter_coverage) or tuple(compute_chapter_coverage(inv))
        object.__setattr__(self, "chapter_coverage", coverage)
        covered_ids = {c.chapter_id for c in coverage if c.section_level_count > 0}
        missing = REQUIRED_CHAPTER_IDS - covered_ids
        if missing:
            raise IncompleteChapterCoverageError(
                "chapter_coverage missing section-level entries for: "
                + ", ".join(sorted(missing))
            )

        expected_counts = compute_counts(
            inv, supersessions=self.supersessions, gaps=self.gaps
        )
        if not isinstance(self.counts, MpepFullInventoryCounts):
            raise MpepFullSectionError("counts must be MpepFullInventoryCounts")
        if self.counts.chapters_required != expected_counts.chapters_required:
            raise SchemaValidationError(
                "counts.chapters_required must equal the required chapter catalog size"
            )
        if self.counts.chapters_covered < len(REQUIRED_CHAPTER_IDS):
            raise IncompleteChapterCoverageError(
                "counts.chapters_covered must include every required chapter"
            )
        if self.counts.section_level_entries < 1:
            raise ChapterOnlyInventoryError(
                "counts.section_level_entries must be >= 1"
            )

        object.__setattr__(
            self,
            "inventory_digest_sha256",
            _require_sha256(self.inventory_digest_sha256, "inventory_digest_sha256"),
        )
        object.__setattr__(
            self,
            "package_digest_sha256",
            _require_sha256(self.package_digest_sha256, "package_digest_sha256"),
        )
        cid = _require_non_empty_str(self.package_root_cid, "package_root_cid", max_len=256)
        if not _CID_RE.fullmatch(cid):
            raise MpepFullSectionError("package_root_cid must be a CIDv1 base32 token")
        object.__setattr__(self, "package_root_cid", cid)

        if self.partition != "public":
            raise SchemaValidationError("partition must be 'public'")
        if self.mode not in {"dry_run", "stage", "acquire"}:
            raise SchemaValidationError(f"unsupported mode: {self.mode!r}")
        if self.staged_at_utc is not None:
            text = _require_non_empty_str(self.staged_at_utc, "staged_at_utc", max_len=64)
            if not _RFC3339_UTC_RE.fullmatch(text):
                raise MpepFullSectionError("staged_at_utc must be RFC3339 UTC")
            object.__setattr__(self, "staged_at_utc", text)
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes", max_len=4096)
            )
        if not isinstance(self.metadata, Mapping):
            raise MpepFullSectionError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        # Verify inventory digest binds the inventory payload.
        inv_digest = content_digest_of([e.to_dict() for e in inv])
        if inv_digest != self.inventory_digest_sha256:
            raise SchemaValidationError(
                "inventory_digest_sha256 does not match canonical inventory payload"
            )

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "chapter_coverage": [c.to_dict() for c in self.chapter_coverage],
                "code_version": self.code_version,
                "config_id": self.config_id,
                "counts": self.counts.to_dict(),
                "edition_pin": self.edition_pin.to_dict(),
                "gaps": [g.to_dict() for g in self.gaps] or None,
                "goal_id": self.goal_id,
                "interface": self.interface,
                "inventory": [e.to_dict() for e in self.inventory],
                "inventory_digest_sha256": self.inventory_digest_sha256,
                "is_binding": False,
                "metadata": _deep_sorted(self.metadata) or None,
                "mode": self.mode,
                "notes": self.notes,
                "package_digest_sha256": self.package_digest_sha256,
                "package_root_cid": self.package_root_cid,
                "partition": self.partition,
                "producer": self.producer,
                "schema_version": self.schema_version,
                "staged_at_utc": self.staged_at_utc,
                "supersessions": [s.to_dict() for s in self.supersessions] or None,
                "task_id": self.task_id,
            }
        )


    @classmethod
    def from_dict(cls, value: JsonMapping) -> "MpepFullInventoryManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        edition_raw = value.get("edition_pin") or value.get("edition")
        if not isinstance(edition_raw, Mapping):
            raise EditionPinError("edition_pin is required and must be a mapping")
        inv_raw = value.get("inventory")
        if not isinstance(inv_raw, list) or not inv_raw:
            raise IncompleteChapterCoverageError(
                "inventory must be a non-empty array of section anchors"
            )
        inventory = tuple(MpepSectionInventoryEntry.from_dict(e) for e in inv_raw)
        coverage_raw = value.get("chapter_coverage")
        if isinstance(coverage_raw, list) and coverage_raw:
            coverage = tuple(MpepChapterCoverage.from_dict(c) for c in coverage_raw)
        else:
            coverage = tuple(compute_chapter_coverage(inventory))
        counts_raw = value.get("counts")
        if isinstance(counts_raw, Mapping):
            counts = MpepFullInventoryCounts.from_dict(counts_raw)
        else:
            supers = tuple(
                MpepSupersessionRecord.from_dict(s)
                for s in (value.get("supersessions") or [])
            )
            gaps = tuple(
                MpepInventoryGap.from_dict(g) for g in (value.get("gaps") or [])
            )
            counts = compute_counts(inventory, supersessions=supers, gaps=gaps)
        supersessions = tuple(
            MpepSupersessionRecord.from_dict(s)
            for s in (value.get("supersessions") or [])
        )
        gaps = tuple(MpepInventoryGap.from_dict(g) for g in (value.get("gaps") or []))
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            edition_pin=MpepEditionPin.from_dict(edition_raw),
            inventory=inventory,
            chapter_coverage=coverage,
            counts=counts,
            inventory_digest_sha256=str(value.get("inventory_digest_sha256") or ""),
            package_digest_sha256=str(value.get("package_digest_sha256") or ""),
            package_root_cid=str(value.get("package_root_cid") or ""),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            supersessions=supersessions,
            gaps=gaps,
            partition=str(value.get("partition") or "public"),
            mode=str(value.get("mode") or "dry_run"),
            staged_at_utc=value.get("staged_at_utc"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


def build_mpep_full_manifest(
    *,
    edition_pin: MpepEditionPin,
    inventory: Sequence[MpepSectionInventoryEntry],
    supersessions: Sequence[MpepSupersessionRecord] = (),
    gaps: Sequence[MpepInventoryGap] = (),
    mode: str = "dry_run",
    notes: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    staged_at_utc: Optional[str] = None,
) -> MpepFullInventoryManifest:
    """Build a validated full MPEP inventory manifest with content digests."""
    inv = tuple(inventory)
    supers = tuple(supersessions)
    gap_t = tuple(gaps)
    coverage = tuple(compute_chapter_coverage(inv))
    counts = compute_counts(inv, supersessions=supers, gaps=gap_t)
    inv_digest = content_digest_of([e.to_dict() for e in inv])
    package_payload = {
        "edition_pin": edition_pin.to_dict(),
        "inventory_digest_sha256": inv_digest,
        "counts": counts.to_dict(),
        "supersessions": [s.to_dict() for s in supers],
        "gaps": [g.to_dict() for g in gap_t],
    }
    package_digest = content_digest_of(package_payload)
    return MpepFullInventoryManifest(
        edition_pin=edition_pin,
        inventory=inv,
        chapter_coverage=coverage,
        counts=counts,
        inventory_digest_sha256=inv_digest,
        package_digest_sha256=package_digest,
        package_root_cid=cid_from_digest(package_digest),
        supersessions=supers,
        gaps=gap_t,
        mode=mode,
        notes=notes,
        metadata=dict(metadata or {}),
        staged_at_utc=staged_at_utc,
    )


def build_compact_full_inventory_fixture(
    *,
    edition: str = "9",
    revision: str = "07.2022",
    cutoff: str | date = "2022-07-01",
    include_form_paragraphs: bool = True,
    include_supersession: bool = True,
) -> dict[str, Any]:
    """Build a compact offline inventory covering every required chapter.

    One section-level (or appendix/index) anchor per required chapter, plus a
    couple of form-paragraph anchors. Suitable for unit tests and dry-runs;
    not a substitute for live full-manual acquisition (PATLAW-183).
    """
    pin = MpepEditionPin(
        edition=edition,
        revision=revision,
        cutoff=cutoff,
        provider="uspto",
        publication_date=cutoff if isinstance(cutoff, date) else date.fromisoformat(str(cutoff)[:10]),
        source_url="https://www.uspto.gov/web/offices/pac/mpep/index.html",
        notes=f"MPEP {edition} Edition, Revision {revision} (compact fixture)",
    )
    inventory: list[MpepSectionInventoryEntry] = []
    for spec in REQUIRED_MPEP_CHAPTERS:
        anchor = _FIXTURE_SECTION_BY_CHAPTER[spec.chapter_id]
        if spec.chapter_id.startswith("appx-"):
            kind = InventoryEntryKind.APPENDIX_ANCHOR
            citation = f"MPEP {spec.chapter_id} / {anchor}"
        elif spec.chapter_id == "index":
            kind = InventoryEntryKind.INDEX_ANCHOR
            citation = "MPEP Index"
        else:
            kind = InventoryEntryKind.MPEP_SECTION
            citation = f"MPEP § {anchor}"
        body = f"fixture:{spec.chapter_id}:{anchor}:{edition}:r{revision}"
        digest = content_sha256(body)
        inventory.append(
            MpepSectionInventoryEntry(
                entry_id=f"mpep-{spec.chapter_id}-{anchor}",
                chapter_id=spec.chapter_id,
                section_anchor=anchor,
                kind=kind,
                status=InventoryEntryStatus.PRESENT,
                title=spec.title,
                citation=citation,
                source_url=(
                    f"https://www.uspto.gov/web/offices/pac/mpep/s{anchor}.html"
                    if kind is InventoryEntryKind.MPEP_SECTION
                    else "https://www.uspto.gov/web/offices/pac/mpep/index.html"
                ),
                content_sha256=digest,
                content_cid=cid_from_digest(digest),
                media_type="text/html",
            )
        )

    if include_form_paragraphs:
        for fp, ch, title in (
            ("7.05", "700", "Rejection, 35 U.S.C. 101, Non-Statutory"),
            ("7.21", "700", "Rejection, 35 U.S.C. 102"),
        ):
            body = f"fixture:fp:{fp}:{edition}:r{revision}"
            digest = content_sha256(body)
            inventory.append(
                MpepSectionInventoryEntry(
                    entry_id=f"fp-{fp}",
                    chapter_id=ch,
                    section_anchor=fp,
                    kind=InventoryEntryKind.FORM_PARAGRAPH,
                    status=InventoryEntryStatus.PRESENT,
                    title=title,
                    citation=f"Form Paragraph {fp}",
                    source_url="https://www.uspto.gov/web/offices/pac/mpep/index.html",
                    content_sha256=digest,
                    content_cid=cid_from_digest(digest),
                    media_type="text/html",
                )
            )

    supersessions: list[MpepSupersessionRecord] = []
    if include_supersession:
        supersessions.append(
            MpepSupersessionRecord(
                successor_id="exam-guide-1-23",
                predecessor_id="mpep-700-706.02",
                relation=SupersessionRelation.SUPERSEDES,
                effective_date=date(2023, 3, 15),
                reason=(
                    "Examination Guide 1-23 supersedes inconsistent MPEP § 706.02 "
                    "manual text for listed scenarios; both remain guidance, not law."
                ),
            )
        )

    manifest = build_mpep_full_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=supersessions,
        mode="dry_run",
        notes=(
            "Compact full-chapter section inventory fixture for PATLAW-182. "
            "Guidance only; never binding law. Chapter-only crawls do not satisfy."
        ),
    )
    return manifest.to_dict()


def validate_manifest_dict(value: JsonMapping) -> MpepFullInventoryManifest:
    """Validate a mapping as a full MPEP inventory manifest (Python contracts)."""
    return MpepFullInventoryManifest.from_dict(value)


def validate_manifest_against_json_schema(
    value: JsonMapping,
    *,
    schema: Mapping[str, Any] | None = None,
) -> None:
    """Validate *value* against the release JSON Schema when jsonschema is present.

    Raises SchemaValidationError on failure. If jsonschema is not installed,
    performs Python-side validation only (still fail-closed on contract errors).
    """
    # Always run Python contracts first (authoritative for domain rules).
    validate_manifest_dict(value)
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return
    schema_obj = schema if schema is not None else load_manifest_schema()
    try:
        jsonschema.Draft202012Validator.check_schema(schema_obj)
        validator = jsonschema.Draft202012Validator(schema_obj)
        errors = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
    except Exception as exc:  # pragma: no cover
        raise SchemaValidationError(f"jsonschema validation failed: {exc}") from exc
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise SchemaValidationError(
            f"manifest fails JSON Schema at {path}: {first.message}"
        )


def iter_required_chapter_ids() -> Iterator[str]:
    """Yield required chapter ids in catalog order."""
    for spec in REQUIRED_MPEP_CHAPTERS:
        yield spec.chapter_id


def mpep_source_url(*, section: Any | None = None) -> str:
    """Documentation default for USPTO MPEP HTML anchors (never 'latest')."""
    if section is None:
        return "https://www.uspto.gov/web/offices/pac/mpep/index.html"
    sec = normalize_mpep_section(section)
    if re.match(r"^\d", sec):
        return f"https://www.uspto.gov/web/offices/pac/mpep/s{sec}.html"
    return "https://www.uspto.gov/web/offices/pac/mpep/index.html"


__all__ = [
    "AUTHORITY_TIER_GUIDANCE",
    "CODE_VERSION",
    "CONFIG_ID",
    "GOAL_ID",
    "INTERFACE",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_FILENAME",
    "PRODUCER",
    "REQUIRED_CHAPTER_BY_ID",
    "REQUIRED_CHAPTER_IDS",
    "REQUIRED_MPEP_CHAPTERS",
    "SCHEMA_VERSION",
    "TASK_ID",
    "BindingElevationError",
    "ChapterOnlyInventoryError",
    "EditionPinError",
    "GapKind",
    "IncompleteChapterCoverageError",
    "InventoryEntryKind",
    "InventoryEntryStatus",
    "MissingCutoffError",
    "MpepChapterCoverage",
    "MpepChapterSpec",
    "MpepEditionPin",
    "MpepFullInventoryCounts",
    "MpepFullInventoryManifest",
    "MpepFullSectionError",
    "MpepInventoryGap",
    "MpepSectionInventoryEntry",
    "MpepSupersessionRecord",
    "SchemaValidationError",
    "SupersessionRelation",
    "assert_guidance_not_elevated",
    "build_compact_full_inventory_fixture",
    "build_mpep_full_manifest",
    "canonical_json",
    "chapter_id_for_section",
    "chapters_with_section_level_coverage",
    "cid_from_digest",
    "compute_chapter_coverage",
    "compute_counts",
    "content_digest_of",
    "content_sha256",
    "default_manifest_schema_path",
    "is_chapter_landing_anchor",
    "is_section_level_anchor",
    "iter_required_chapter_ids",
    "load_manifest_schema",
    "mpep_source_url",
    "normalize_chapter_id",
    "normalize_form_paragraph",
    "normalize_mpep_section",
    "parse_mpep_edition_revision",
    "stable_section_identity",
    "validate_full_chapter_coverage",
    "validate_inventory_not_chapter_only",
    "validate_manifest_against_json_schema",
    "validate_manifest_dict",
]
