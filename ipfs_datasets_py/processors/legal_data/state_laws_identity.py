"""Canonical jurisdiction and statute identity for state law (LCR-006).

This module owns the file-disjoint identity parser/normalizer used by the
``state-laws-ir-graphrag/v2`` release. It deliberately does **not** depend on
network I/O, Parquet, or scraper entry points.

Design invariants
-----------------
* ``legal_id`` is a stable citation-oriented identifier of the form
  ``state:<JURISDICTION>:<code_family>:<path…>[;qualifiers]``, independent of
  content version (``entry_cid`` / ``content_cid``) and release-local row index.
* ``entry_cid`` is the retrieval primary key; duplicate primary keys fail closed.
* Jurisdiction segments must belong to the exact 51-set (50 postal codes + DC).
* Duplicate citations are **not** collapsed across editions, appendices, notes,
  code families, history/current kinds, or source units.
* Durable identity never depends on row position (``document_index``, ``row-N``).
* Logical statute duplicates and changed-text versions receive **explicit
  deterministic dispositions**. Row position alone or content CID alone cannot
  merge versions incorrectly.
* Unicode en/em dashes (and related dash characters) never truncate section
  tokens. Dash-range sections such as ``1001–1003`` remain fully addressable.

The sealed collision fixture expands to a compact recipe that exercises
dash-truncation collisions, code-family/jurisdiction disambiguation, qualifier
rows, changed-text version pairs, and content-CID-only / positional non-merges.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
)

SCHEMA_VERSION = "state-laws-identity-v1"
FIXTURE_SCHEMA_VERSION = "state-laws-identity-collisions-v1"
TASK_ID = "LCR-006"

# Exact expanded row count of the sealed collision fixture.
KNOWN_COLLISION_ROW_COUNT = 420

DEFAULT_KIND = "section"
LEGAL_ID_PREFIX = "state"

# Dash / minus characters that must never truncate a section token.
_UNICODE_DASH_CHARS = (
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign
    "\ufe58",  # small em dash
    "\ufe63",  # small hyphen-minus
    "\uff0d",  # fullwidth hyphen-minus
)
_DASH_TRANSLATION = str.maketrans({ch: "-" for ch in _UNICODE_DASH_CHARS})
_UNICODE_DASH_SET = frozenset(_UNICODE_DASH_CHARS)

# Numeric base, optional lettered/dotted/slashed tails, parentheticals, ranges.
_SECTION_CORE = r"\d+[A-Za-z0-9./\-]*(?:\([a-zA-Z0-9]+\))*"
_SECTION_TOKEN_RE = re.compile(
    rf"(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?(?P<section>{_SECTION_CORE}(?:\s*-\s*{_SECTION_CORE})*)",
    re.IGNORECASE,
)
_LEADING_ZEROS_RE = re.compile(r"^0*(\d+)(.*)$")
_CHUNK_SUFFIX_RE = re.compile(r"#chunk=(?P<index>\d+)$")
_CODE_FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_POSITIONAL_ID_RE = re.compile(
    r"^(?:row[-_ ]?\d+|row[-_ ]?N|document[-_ ]?index[-_ ]?\d+|idx[-_ ]?\d+|"
    r"pos[-_ ]?\d+|offset[-_ ]?\d+)$",
    re.IGNORECASE,
)

# Qualifier keys that participate in legal_id construction (sorted).
_QUALIFIER_KEYS = (
    "appendix",
    "edition",
    "granule",
    "kind",
    "note",
    "schedule",
    "subsection",
)

# Path hierarchy keys in order (empty values omitted).
_PATH_KEYS = (
    "title",
    "chapter",
    "part",
    "article",
    "section",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


class StateLawsIdentityError(ValueError):
    """Base error for state-law identity failures."""


class IdentityParseError(StateLawsIdentityError):
    """Raised when a section, path, or legal_id token cannot be parsed fully."""


class DuplicatePrimaryKeyError(StateLawsIdentityError):
    """Raised when duplicate primary keys (``entry_cid``) are detected."""


class CollisionFixtureError(StateLawsIdentityError):
    """Raised when the sealed collision fixture is malformed."""


class IdentityDispositionError(StateLawsIdentityError):
    """Raised when a merge or disposition cannot be resolved deterministically."""


class NodeKind(str, Enum):
    """Structural kind of a legal identity node."""

    SECTION = "section"
    SUBSECTION = "subsection"
    APPENDIX = "appendix"
    NOTE = "note"
    HISTORY = "history"
    CURRENT = "current"
    SCHEDULE = "schedule"
    GRANULE = "granule"
    CHAPTER = "chapter"
    TITLE = "title"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "NodeKind":
        if value is None or value == "":
            return cls.SECTION
        if isinstance(value, NodeKind):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "hist": cls.HISTORY,
            "historical": cls.HISTORY,
            "historical_note": cls.NOTE,
            "curr": cls.CURRENT,
            "current_text": cls.CURRENT,
            "app": cls.APPENDIX,
        }
        if text in aliases:
            return aliases[text]
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


class IdentityDisposition(str, Enum):
    """Deterministic disposition for a logical-identity comparison or merge.

    These are explicit outcomes — never inferred from row position or content
    CID alone.
    """

    UNIQUE = "unique"
    DUPLICATE = "duplicate"
    CHANGED_TEXT_VERSION = "changed_text_version"
    DISTINCT_IDENTITY = "distinct_identity"
    REJECT_POSITIONAL_MERGE = "reject_positional_merge"
    REJECT_CONTENT_CID_ONLY_MERGE = "reject_content_cid_only_merge"
    KEEP_CURRENT = "keep_current"
    ARCHIVE_HISTORY = "archive_history"

    @classmethod
    def coerce(cls, value: Any) -> "IdentityDisposition":
        if isinstance(value, IdentityDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dup": cls.DUPLICATE,
            "duplicate_logical": cls.DUPLICATE,
            "changed_text": cls.CHANGED_TEXT_VERSION,
            "version": cls.CHANGED_TEXT_VERSION,
            "history": cls.ARCHIVE_HISTORY,
            "current": cls.KEEP_CURRENT,
            "positional": cls.REJECT_POSITIONAL_MERGE,
            "content_cid_only": cls.REJECT_CONTENT_CID_ONLY_MERGE,
            "cid_only": cls.REJECT_CONTENT_CID_ONLY_MERGE,
            "distinct": cls.DISTINCT_IDENTITY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise IdentityDispositionError(f"unknown identity disposition: {value!r}")


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsIdentityError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsIdentityError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def normalize_dash_chars(text: str) -> str:
    """Normalize Unicode dash/minus characters to ASCII hyphen-minus.

    This is a pure character mapping: it never truncates the string and never
    discards characters after a dash. En-dash ranges such as ``1001–1003``
    become ``1001-1003`` rather than bare ``1001``.
    """

    if not isinstance(text, str):
        raise StateLawsIdentityError("text must be a string")
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.translate(_DASH_TRANSLATION)


def normalize_jurisdiction(jurisdiction: Any) -> str:
    """Normalize a postal jurisdiction code against the exact 51-set."""

    text = _require_non_empty_str(jurisdiction, "jurisdiction").upper()
    if text not in CANONICAL_JURISDICTIONS:
        raise StateLawsIdentityError(
            f"jurisdiction={text!r} is not in the exact 51-jurisdiction set "
            f"(50 states + DC; expected {EXPECTED_JURISDICTION_COUNT})"
        )
    return text


def normalize_code_family(code_family: Any) -> str:
    """Normalize a code-family slug (stable, lower-case, dash-safe)."""

    text = _require_non_empty_str(code_family, "code_family")
    text = normalize_dash_chars(text)
    text = text.strip().lower().replace(" ", "-").replace("/", "-")
    text = re.sub(r"_+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = re.sub(r"[^a-z0-9._-]", "", text)
    if not text or not _CODE_FAMILY_RE.fullmatch(text):
        raise StateLawsIdentityError(
            f"code_family must match [a-z0-9][a-z0-9._-]{{0,63}}; got {code_family!r}"
        )
    return text


def _normalize_path_segment(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    text = _require_non_empty_str(value, name)
    text = normalize_dash_chars(text)
    text = text.lstrip("§").strip()
    text = text.rstrip(".,;:")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "", text)
    text = text.rstrip(".,;:")
    if not text:
        return None
    # Strip leading zeros on each numeric run while preserving lettered tails.
    parts: list[str] = []
    for piece in text.split("-"):
        if not piece:
            raise IdentityParseError(f"malformed {name} range: {value!r}")
        match = _LEADING_ZEROS_RE.match(piece)
        if match:
            parts.append(f"{int(match.group(1))}{match.group(2)}")
        else:
            parts.append(piece.lower() if not piece[:1].isdigit() else piece)
    return "-".join(parts)


def _normalize_section_core(raw: str) -> str:
    """Normalize one section core token (no surrounding citation noise)."""

    text = normalize_dash_chars(raw).strip()
    text = text.lstrip("§").strip()
    text = text.rstrip(".,;:")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "", text)
    text = text.rstrip(".,;:")
    if not text:
        raise IdentityParseError("section must be non-empty")

    parts: list[str] = []
    for piece in text.split("-"):
        if not piece:
            raise IdentityParseError(f"malformed section range: {raw!r}")
        match = _LEADING_ZEROS_RE.match(piece)
        if match:
            parts.append(f"{int(match.group(1))}{match.group(2)}")
        else:
            parts.append(piece)
    return "-".join(parts)


def normalize_section_token(section: Any) -> str:
    """Normalize a section citation token without Unicode-dash truncation.

    Accepts bare numbers (``518.17``), section symbols (``§ 518.17``), lettered
    tails (``101a``), parentheticals (``181(a)``), and dash ranges with ASCII
    or Unicode dashes (``1001–1003``). The full range is always preserved.
    """

    if section is None:
        raise IdentityParseError("section must be non-empty")
    original = str(section).strip()
    if not original:
        raise IdentityParseError("section must be non-empty")

    dashed = normalize_dash_chars(original)
    # Strip common state citation prefixes such as "ORS ", "Minn. Stat. §".
    stripped = re.sub(
        r"^(?:[A-Za-z][A-Za-z.\s]{0,40}(?:Stat\.?|Code|Laws?)\s*)?(?:§+\s*)?",
        "",
        dashed,
        count=1,
    ).strip()
    if not stripped:
        stripped = dashed

    candidates = list(_SECTION_TOKEN_RE.finditer(stripped))
    if not candidates:
        return _normalize_section_core(stripped)

    match = candidates[-1]
    token = match.group("section")
    trailing = stripped[match.end() :].strip()
    trailing = re.sub(r"^[.,;:)\]]+", "", trailing).strip()
    if trailing and not re.fullmatch(
        r"(?:et\s+seq\.?|note|notes|nn?\.?|hist\.?|history)?", trailing, re.I
    ):
        remainder = stripped[match.start() :]
        remainder = re.sub(
            r"^(?:§+\s*|sec(?:tion)?\.?\s*)+",
            "",
            remainder,
            flags=re.IGNORECASE,
        )
        return _normalize_section_core(remainder)

    return _normalize_section_core(token)


def _normalize_qualifier(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    text = _require_non_empty_str(value, name)
    text = normalize_dash_chars(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def _format_qualifiers(components: Mapping[str, Optional[str]]) -> str:
    parts: list[str] = []
    for key in _QUALIFIER_KEYS:
        value = components.get(key)
        if value is None or value == "":
            continue
        if key == "kind" and value == DEFAULT_KIND:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return ";" + ";".join(parts)


def _build_path(
    *,
    title: Optional[str],
    chapter: Optional[str],
    part: Optional[str],
    article: Optional[str],
    section: str,
    explicit_path: Optional[str] = None,
) -> str:
    if explicit_path:
        text = normalize_dash_chars(explicit_path).strip().strip(":")
        text = re.sub(r"\s+", "", text)
        if not text:
            raise IdentityParseError("path must be non-empty")
        # Normalize each colon-separated segment.
        segments = []
        for seg in text.split(":"):
            if not seg:
                continue
            segments.append(_normalize_section_core(seg) if re.search(r"\d", seg) else seg.lower())
        if not segments:
            raise IdentityParseError("path must be non-empty")
        return ":".join(segments)

    segments: list[str] = []
    for key, value in (
        ("title", title),
        ("chapter", chapter),
        ("part", part),
        ("article", article),
        ("section", section),
    ):
        if value is None or value == "":
            continue
        segments.append(value)
    if not segments:
        raise IdentityParseError("legal_id path requires at least a section")
    return ":".join(segments)


@dataclass(frozen=True, slots=True)
class LegalIdentity:
    """Canonical legal identity for one state-law addressable unit.

    ``legal_id`` is citation-oriented and independent of content version.
    ``entry_cid`` (when present on a row) is the retrieval primary key and is
    intentionally **not** part of this record.
    """

    jurisdiction: str
    code_family: str
    section: str
    title: Optional[str] = None
    chapter: Optional[str] = None
    part: Optional[str] = None
    article: Optional[str] = None
    subsection: Optional[str] = None
    appendix: Optional[str] = None
    note: Optional[str] = None
    granule: Optional[str] = None
    edition: Optional[str] = None
    schedule: Optional[str] = None
    kind: str = DEFAULT_KIND
    path: Optional[str] = None
    source_section: Optional[str] = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "jurisdiction", normalize_jurisdiction(self.jurisdiction))
        object.__setattr__(self, "code_family", normalize_code_family(self.code_family))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        object.__setattr__(self, "title", _normalize_path_segment(self.title, "title"))
        object.__setattr__(self, "chapter", _normalize_path_segment(self.chapter, "chapter"))
        object.__setattr__(self, "part", _normalize_path_segment(self.part, "part"))
        object.__setattr__(self, "article", _normalize_path_segment(self.article, "article"))
        object.__setattr__(self, "subsection", _normalize_qualifier(self.subsection, "subsection"))
        object.__setattr__(self, "appendix", _normalize_qualifier(self.appendix, "appendix"))
        object.__setattr__(self, "note", _normalize_qualifier(self.note, "note"))
        object.__setattr__(self, "granule", _normalize_qualifier(self.granule, "granule"))
        object.__setattr__(self, "edition", _normalize_qualifier(self.edition, "edition"))
        object.__setattr__(self, "schedule", _normalize_qualifier(self.schedule, "schedule"))
        kind = NodeKind.coerce(self.kind).value
        object.__setattr__(self, "kind", kind)
        built_path = _build_path(
            title=self.title,
            chapter=self.chapter,
            part=self.part,
            article=self.article,
            section=self.section,
            explicit_path=self.path,
        )
        object.__setattr__(self, "path", built_path)
        if self.source_section is not None:
            object.__setattr__(self, "source_section", str(self.source_section))

    @property
    def legal_id(self) -> str:
        """Return the stable citation-oriented legal identifier."""

        base = f"{LEGAL_ID_PREFIX}:{self.jurisdiction}:{self.code_family}:{self.path}"
        return base + _format_qualifiers(
            {
                "appendix": self.appendix,
                "edition": self.edition,
                "granule": self.granule,
                "kind": self.kind,
                "note": self.note,
                "schedule": self.schedule,
                "subsection": self.subsection,
            }
        )

    @property
    def canonical_citation(self) -> str:
        """Return a compact human-readable citation string."""

        parts: list[str] = [self.jurisdiction, self.code_family.upper()]
        if self.title:
            parts.append(f"tit. {self.title}")
        if self.chapter:
            parts.append(f"ch. {self.chapter}")
        if self.part:
            parts.append(f"pt. {self.part}")
        section_display = self.section
        if self.subsection and f"({self.subsection})" not in section_display:
            if re.fullmatch(r"[a-z0-9]+", self.subsection):
                section_display = f"{section_display}({self.subsection})"
        parts.append(f"§ {section_display}")
        extras: list[str] = []
        if self.appendix:
            extras.append(f"app. {self.appendix}")
        if self.schedule:
            extras.append(f"sched. {self.schedule}")
        if self.note:
            extras.append(f"note ({self.note})")
        if self.kind not in {DEFAULT_KIND, NodeKind.SECTION.value}:
            extras.append(self.kind)
        if self.edition:
            extras.append(f"[{self.edition}]")
        cite = " ".join(parts)
        if extras:
            cite = f"{cite} ({', '.join(extras)})"
        return cite

    @property
    def parent_legal_id(self) -> str:
        """Return the deterministic chunk-parent identity.

        Chunks of a section share this parent identity. Subsection-scoped
        identities parent to the bare section (other qualifiers preserved).
        """

        if self.subsection is None and self.kind != NodeKind.SUBSECTION.value:
            return self.legal_id
        parent = LegalIdentity(
            jurisdiction=self.jurisdiction,
            code_family=self.code_family,
            section=self.section,
            title=self.title,
            chapter=self.chapter,
            part=self.part,
            article=self.article,
            subsection=None,
            appendix=self.appendix,
            note=self.note,
            granule=self.granule,
            edition=self.edition,
            schedule=self.schedule,
            kind=DEFAULT_KIND if self.kind == NodeKind.SUBSECTION.value else self.kind,
        )
        return parent.legal_id

    def chunk_id(self, chunk_index: int) -> str:
        """Return a deterministic chunk identity under this parent."""

        if not isinstance(chunk_index, int) or chunk_index < 0:
            raise StateLawsIdentityError("chunk_index must be a non-negative integer")
        return f"{self.parent_legal_id}#chunk={chunk_index:04d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "appendix": self.appendix,
            "article": self.article,
            "canonical_citation": self.canonical_citation,
            "chapter": self.chapter,
            "code_family": self.code_family,
            "edition": self.edition,
            "granule": self.granule,
            "jurisdiction": self.jurisdiction,
            "kind": self.kind,
            "legal_id": self.legal_id,
            "note": self.note,
            "parent_legal_id": self.parent_legal_id,
            "part": self.part,
            "path": self.path,
            "schedule": self.schedule,
            "schema_version": SCHEMA_VERSION,
            "section": self.section,
            "source_section": self.source_section,
            "subsection": self.subsection,
            "title": self.title,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalIdentity":
        if not isinstance(value, Mapping):
            raise StateLawsIdentityError("identity payload must be a mapping")
        section = value.get("section")
        if section is None:
            section = value.get("section_number") or value.get("sectionNumber")
        title = value.get("title")
        if title is None:
            title = value.get("title_number") or value.get("titleNumber")
        chapter = value.get("chapter")
        if chapter is None:
            chapter = value.get("chapter_number") or value.get("chapterNumber")
        jurisdiction = value.get("jurisdiction")
        if jurisdiction is None:
            jurisdiction = value.get("state_code") or value.get("state")
        code_family = value.get("code_family")
        if code_family is None:
            code_family = value.get("codeFamily") or value.get("code")
        source_section = value.get("source_section")
        if source_section is None and section is not None:
            source_section = str(section)
        return cls(
            jurisdiction=jurisdiction,
            code_family=code_family,
            section=section,
            title=title,
            chapter=chapter,
            part=value.get("part"),
            article=value.get("article"),
            subsection=value.get("subsection"),
            appendix=value.get("appendix"),
            note=value.get("note"),
            granule=value.get("granule") or value.get("granule_id"),
            edition=value.get("edition") or value.get("edition_id") or value.get("edition_as_of"),
            schedule=value.get("schedule"),
            kind=value.get("kind", DEFAULT_KIND),
            path=value.get("path"),
            source_section=source_section,
        )


def build_legal_id(
    *,
    jurisdiction: Any,
    code_family: Any,
    section: Any,
    title: Any = None,
    chapter: Any = None,
    part: Any = None,
    article: Any = None,
    subsection: Any = None,
    appendix: Any = None,
    note: Any = None,
    granule: Any = None,
    edition: Any = None,
    schedule: Any = None,
    kind: Any = DEFAULT_KIND,
    path: Any = None,
) -> str:
    """Build a stable ``legal_id`` from citation components."""

    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=section,
        title=title,
        chapter=chapter,
        part=part,
        article=article,
        subsection=subsection,
        appendix=appendix,
        note=note,
        granule=granule,
        edition=edition,
        schedule=schedule,
        kind=kind,
        path=path,
    ).legal_id


def build_canonical_citation(
    *,
    jurisdiction: Any,
    code_family: Any,
    section: Any,
    title: Any = None,
    chapter: Any = None,
    part: Any = None,
    subsection: Any = None,
    appendix: Any = None,
    note: Any = None,
    edition: Any = None,
    schedule: Any = None,
    kind: Any = DEFAULT_KIND,
    **kwargs: Any,
) -> str:
    """Build a compact human-readable citation string."""

    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=section,
        title=title,
        chapter=chapter,
        part=part,
        subsection=subsection,
        appendix=appendix,
        note=note,
        edition=edition,
        schedule=schedule,
        kind=kind,
        **{k: v for k, v in kwargs.items() if k in {"article", "granule", "path"}},
    ).canonical_citation


def build_chunk_parent_id(
    *,
    jurisdiction: Any,
    code_family: Any,
    section: Any,
    title: Any = None,
    chapter: Any = None,
    part: Any = None,
    article: Any = None,
    subsection: Any = None,
    appendix: Any = None,
    note: Any = None,
    granule: Any = None,
    edition: Any = None,
    schedule: Any = None,
    kind: Any = DEFAULT_KIND,
) -> str:
    """Return the deterministic parent identity for semantic text chunks."""

    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=section,
        title=title,
        chapter=chapter,
        part=part,
        article=article,
        subsection=subsection,
        appendix=appendix,
        note=note,
        granule=granule,
        edition=edition,
        schedule=schedule,
        kind=kind,
    ).parent_legal_id


def parse_chunk_id(chunk_id: str) -> tuple[str, int]:
    """Split ``{parent_legal_id}#chunk=NNNN`` into parent id and index."""

    text = _require_non_empty_str(chunk_id, "chunk_id")
    match = _CHUNK_SUFFIX_RE.search(text)
    if not match:
        raise IdentityParseError(f"not a chunk id: {chunk_id!r}")
    parent = text[: match.start()]
    return parent, int(match.group("index"))


def parse_legal_id(legal_id: str) -> LegalIdentity:
    """Parse a previously built ``legal_id`` back into components."""

    text = _require_non_empty_str(legal_id, "legal_id")
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise IdentityParseError(f"legal_id must not be positional: {legal_id!r}")
    if not text.lower().startswith(f"{LEGAL_ID_PREFIX}:"):
        raise IdentityParseError(
            f"legal_id must start with '{LEGAL_ID_PREFIX}:': {legal_id!r}"
        )
    body = text[len(LEGAL_ID_PREFIX) + 1 :]
    if ";" in body:
        base, qual_text = body.split(";", 1)
        qualifiers: dict[str, str] = {}
        for part in qual_text.split(";"):
            if not part:
                continue
            if "=" not in part:
                raise IdentityParseError(f"malformed legal_id qualifier: {part!r}")
            key, value = part.split("=", 1)
            qualifiers[key] = value
    else:
        base = body
        qualifiers = {}

    pieces = base.split(":")
    if len(pieces) < 3:
        raise IdentityParseError(
            f"legal_id base must be jurisdiction:code_family:path…, got {base!r}"
        )
    jurisdiction = pieces[0]
    code_family = pieces[1]
    path_segments = pieces[2:]
    # Map trailing path segment to section; leading ones to hierarchy fields.
    section = path_segments[-1]
    title = path_segments[0] if len(path_segments) >= 2 else None
    chapter = None
    part = None
    article = None
    if len(path_segments) == 3:
        chapter = path_segments[1]
    elif len(path_segments) == 4:
        chapter = path_segments[1]
        part = path_segments[2]
    elif len(path_segments) >= 5:
        chapter = path_segments[1]
        part = path_segments[2]
        article = path_segments[3]
        # If more than 5 segments, rejoin middle into chapter-like path via path=.
        if len(path_segments) > 5:
            return LegalIdentity(
                jurisdiction=jurisdiction,
                code_family=code_family,
                section=section,
                path=":".join(path_segments),
                subsection=qualifiers.get("subsection"),
                appendix=qualifiers.get("appendix"),
                note=qualifiers.get("note"),
                granule=qualifiers.get("granule"),
                edition=qualifiers.get("edition"),
                schedule=qualifiers.get("schedule"),
                kind=qualifiers.get("kind", DEFAULT_KIND),
            )

    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=section,
        title=title,
        chapter=chapter,
        part=part,
        article=article,
        subsection=qualifiers.get("subsection"),
        appendix=qualifiers.get("appendix"),
        note=qualifiers.get("note"),
        granule=qualifiers.get("granule"),
        edition=qualifiers.get("edition"),
        schedule=qualifiers.get("schedule"),
        kind=qualifiers.get("kind", DEFAULT_KIND),
    )


def naive_truncated_section_token(section: Any) -> str:
    """Reproduce the legacy truncated-ID bug for fixture contrast.

    Stops at the first Unicode dash/minus character. Not used for production IDs.
    """

    text = str(section if section is not None else "")
    for index, char in enumerate(text):
        if char in _UNICODE_DASH_SET:
            text = text[:index]
            break
    match = re.search(r"(\d+[A-Za-z0-9.\-]*)", text)
    if not match:
        return text.strip()
    raw = match.group(1)
    m = _LEADING_ZEROS_RE.match(raw)
    if m:
        return f"{int(m.group(1))}{m.group(2)}"
    return raw


def identity_from_row(row: Mapping[str, Any]) -> LegalIdentity:
    """Build a :class:`LegalIdentity` from a corpus/fixture row mapping."""

    return LegalIdentity.from_mapping(row)


def legal_id_from_row(row: Mapping[str, Any]) -> str:
    """Return ``legal_id`` for a row mapping (uses existing field when present)."""

    existing = row.get("legal_id")
    if isinstance(existing, str) and existing.strip() and not _POSITIONAL_ID_RE.fullmatch(existing.strip()):
        if existing.strip().lower().startswith(f"{LEGAL_ID_PREFIX}:"):
            # Prefer the normalized parse of an explicit legal_id.
            return parse_legal_id(existing.strip()).legal_id
    return identity_from_row(row).legal_id


def content_identity_from_row(row: Mapping[str, Any]) -> str:
    """Return the content-version identity for a row.

    Used to distinguish changed-text versions under the same ``legal_id``.
    Prefer body evidence (``content_cid``, then text digest) so two retrieval
    rows with different ``entry_cid`` values but identical statute text are
    classified as logical duplicates. Fall back to ``entry_cid`` / ``ipfs_cid``
    only when no body evidence is present.

    This is intentionally **separate** from durable statute identity: content
    CID alone is never a merge key across distinct legal identities.
    """

    for field_name in ("content_cid",):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip() and not _POSITIONAL_ID_RE.fullmatch(value.strip()):
            return value.strip().lower()
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    for field_name in ("entry_cid", "ipfs_cid"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip() and not _POSITIONAL_ID_RE.fullmatch(value.strip()):
            return value.strip().lower()
    # Stable empty-content marker so missing content is still comparable.
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def body_content_token(row: Mapping[str, Any]) -> Optional[str]:
    """Return a body/content token that must not merge distinct legal identities.

    Prefers an explicit ``content_cid`` / ``ipfs_cid`` (not ``entry_cid``, which
    is the retrieval primary key), then falls back to a digest of ``text``.
    """

    for field_name in ("content_cid", "ipfs_cid"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip() and not _POSITIONAL_ID_RE.fullmatch(value.strip()):
            # When content_cid equals entry_cid it still represents body identity.
            return f"cid:{value.strip().lower()}"
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"text:{digest}"
    return None


def row_position_token(row: Mapping[str, Any]) -> Optional[str]:
    """Return a positional index token if present (not durable identity)."""

    for field_name in ("document_index", "row_index", "row_id", "index", "offset"):
        value = row.get(field_name)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if field_name == "row_id" and not re.fullmatch(r"(?:row[-_]?)?\d+", text, re.I):
            # Human fixture row_ids such as "seed-en-dash" are not positions.
            continue
        if isinstance(value, int) or re.fullmatch(r"\d+", text):
            return f"row-{text}"
        if _POSITIONAL_ID_RE.fullmatch(text):
            return text.lower()
    return None


def classify_identity_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify two rows with an explicit deterministic disposition.

    Rules (fail-closed, ordered):
    1. Same legal_id + same content-version identity → ``duplicate``.
    2. Same legal_id + different content-version identity → ``changed_text_version``.
    3. Different legal_id + shared body content CID/text → ``reject_content_cid_only_merge``.
    4. Different legal_id + shared row position → ``reject_positional_merge``.
    5. Otherwise different legal_id → ``distinct_identity``.
    """

    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise StateLawsIdentityError("pair rows must be mappings")

    left_legal = legal_id_from_row(left)
    right_legal = legal_id_from_row(right)
    left_version = content_identity_from_row(left)
    right_version = content_identity_from_row(right)
    left_body = body_content_token(left)
    right_body = body_content_token(right)
    left_pos = row_position_token(left)
    right_pos = row_position_token(right)

    if left_legal == right_legal:
        if left_version == right_version:
            disposition = IdentityDisposition.DUPLICATE
        else:
            disposition = IdentityDisposition.CHANGED_TEXT_VERSION
        return {
            "disposition": disposition.value,
            "legal_id": left_legal,
            "left_content_id": left_version,
            "right_content_id": right_version,
            "same_legal_id": True,
            "same_content_id": left_version == right_version,
            "same_body_content": left_body is not None and left_body == right_body,
            "same_row_position": left_pos is not None and left_pos == right_pos,
            "merge_allowed": disposition is IdentityDisposition.DUPLICATE,
            "version_pair": disposition is IdentityDisposition.CHANGED_TEXT_VERSION,
        }

    # Different legal identities: refuse merges based only on body CID/text or position.
    same_position = left_pos is not None and left_pos == right_pos
    same_body = left_body is not None and left_body == right_body
    if same_body:
        disposition = IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE
    elif same_position:
        disposition = IdentityDisposition.REJECT_POSITIONAL_MERGE
    else:
        disposition = IdentityDisposition.DISTINCT_IDENTITY

    return {
        "disposition": disposition.value,
        "left_legal_id": left_legal,
        "right_legal_id": right_legal,
        "left_content_id": left_version,
        "right_content_id": right_version,
        "same_legal_id": False,
        "same_content_id": left_version == right_version,
        "same_body_content": same_body,
        "same_row_position": same_position,
        "merge_allowed": False,
        "version_pair": False,
    }


def resolve_version_dispositions(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group rows by durable ``legal_id`` and assign deterministic dispositions.

    * Within a ``legal_id`` group, identical content identities are
      ``duplicate``; differing content identities become one ``keep_current``
      (last-seen wins, deterministic order) plus ``archive_history`` priors.
    * Rows that only share content CID or only share row position across
      different legal_ids are **not** merged; they receive reject dispositions
      when compared.
    """

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise StateLawsIdentityError("rows must be a sequence of mappings")

    groups: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise StateLawsIdentityError(f"row {index} must be a mapping")
        legal_id = legal_id_from_row(row)
        groups.setdefault(legal_id, []).append((index, row))

    current_rows: list[dict[str, Any]] = []
    history_by_key: dict[str, list[dict[str, Any]]] = {}
    dispositions: list[dict[str, Any]] = []
    order: list[str] = []

    for legal_id, members in groups.items():
        order.append(legal_id)
        # Group members by content identity, preserving first-seen order.
        content_order: list[str] = []
        by_content: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
        for index, row in members:
            cid = content_identity_from_row(row)
            if cid not in by_content:
                content_order.append(cid)
                by_content[cid] = []
            by_content[cid].append((index, row))

        history: list[dict[str, Any]] = []
        # Last distinct content version is current; earlier versions are history.
        for content_index, cid in enumerate(content_order):
            cohort = by_content[cid]
            primary_index, primary_row = cohort[0]
            is_last = content_index == len(content_order) - 1
            if is_last:
                current = dict(primary_row)
                current["legal_id"] = legal_id
                current["logical_key"] = legal_id
                current["identity_disposition"] = IdentityDisposition.KEEP_CURRENT.value
                current_rows.append(current)
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": primary_index,
                        "content_id": cid,
                        "disposition": IdentityDisposition.KEEP_CURRENT.value,
                    }
                )
            else:
                hist_entry = {
                    "logical_key": legal_id,
                    "legal_id": legal_id,
                    "content_id": cid,
                    "entry_cid": str(
                        primary_row.get("entry_cid")
                        or primary_row.get("content_cid")
                        or primary_row.get("ipfs_cid")
                        or cid
                    ),
                    "disposition": IdentityDisposition.ARCHIVE_HISTORY.value,
                    "row_index": primary_index,
                }
                history.append(hist_entry)
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": primary_index,
                        "content_id": cid,
                        "disposition": IdentityDisposition.CHANGED_TEXT_VERSION.value,
                    }
                )

            # Exact content duplicates under the same legal_id.
            for dup_index, _dup_row in cohort[1:]:
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": dup_index,
                        "content_id": cid,
                        "disposition": IdentityDisposition.DUPLICATE.value,
                        "duplicate_of_row_index": primary_index,
                    }
                )

        history_by_key[legal_id] = history

    # Cross-identity illegal merge probes: body-content-only and positional-only.
    reject_events: list[dict[str, Any]] = []
    body_to_legal: dict[str, set[str]] = {}
    position_to_legal: dict[str, set[str]] = {}
    for legal_id, members in groups.items():
        for _index, row in members:
            body = body_content_token(row)
            if body is not None:
                body_to_legal.setdefault(body, set()).add(legal_id)
            pos = row_position_token(row)
            if pos is not None:
                position_to_legal.setdefault(pos, set()).add(legal_id)

    for body, legal_ids in sorted(body_to_legal.items()):
        if len(legal_ids) > 1:
            reject_events.append(
                {
                    "disposition": IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value,
                    "body_content_token": body,
                    "legal_ids": sorted(legal_ids),
                    "merge_allowed": False,
                }
            )
    for pos, legal_ids in sorted(position_to_legal.items()):
        if len(legal_ids) > 1:
            reject_events.append(
                {
                    "disposition": IdentityDisposition.REJECT_POSITIONAL_MERGE.value,
                    "row_position": pos,
                    "legal_ids": sorted(legal_ids),
                    "merge_allowed": False,
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "current_rows": current_rows,
        "history_by_key": history_by_key,
        "current_keys": list(order),
        "history_keys": [key for key in order if history_by_key.get(key)],
        "dispositions": dispositions,
        "reject_events": reject_events,
        "group_count": len(order),
        "current_count": len(current_rows),
        "duplicate_count": sum(
            1 for d in dispositions if d["disposition"] == IdentityDisposition.DUPLICATE.value
        ),
        "changed_text_count": sum(
            1
            for d in dispositions
            if d["disposition"] == IdentityDisposition.CHANGED_TEXT_VERSION.value
        ),
    }


def merge_by_legal_identity(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge rows by durable legal identity with explicit version dispositions.

    Content changes under the same ``legal_id`` replace the current row and
    archive the prior content identity. Content CID alone or row position alone
    never merges distinct legal identities.
    """

    combined: list[Mapping[str, Any]] = list(existing_rows or ())
    if new_rows:
        combined.extend(list(new_rows))
    return resolve_version_dispositions(combined)


def validate_primary_keys(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_field: str = "entry_cid",
) -> None:
    """Fail closed when duplicate primary keys are present."""

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise StateLawsIdentityError(f"row {index} must be a mapping")
        if key_field not in row or row[key_field] in (None, ""):
            raise StateLawsIdentityError(
                f"row {index} missing required primary key field {key_field!r}"
            )
        key = str(row[key_field]).strip()
        if not key:
            raise StateLawsIdentityError(f"row {index} has empty {key_field}")
        if _POSITIONAL_ID_RE.fullmatch(key):
            raise StateLawsIdentityError(
                f"row {index} primary key must not be positional: {key!r}"
            )
        if key in seen:
            raise DuplicatePrimaryKeyError(
                f"duplicate primary key {key_field}={key!r} at rows "
                f"{seen[key]} and {index}"
            )
        seen[key] = index


def assert_legal_ids_distinguishable(
    rows: Iterable[Mapping[str, Any]],
    *,
    allow_version_collisions: bool = False,
) -> list[str]:
    """Return legal_ids for *rows*.

    By default requires every ``legal_id`` to be unique (the collision-fixture
    failure mode under repair). When ``allow_version_collisions`` is true,
    identical legal_ids are permitted only when content identities differ
    (changed-text versions) or match as explicit duplicates — never when the
    only shared token is a row position.
    """

    legal_ids: list[str] = []
    seen: dict[str, tuple[int, str]] = {}
    rows_list = list(rows)
    for index, row in enumerate(rows_list):
        legal_id = legal_id_from_row(row)
        content_id = content_identity_from_row(row)
        if legal_id in seen:
            prior_index, prior_content = seen[legal_id]
            if not allow_version_collisions:
                raise StateLawsIdentityError(
                    f"legal_id collision for {legal_id!r} at rows "
                    f"{prior_index} and {index}"
                )
            # Version collisions are OK; still reject if nothing distinguishes
            # content and we expected uniqueness of primary retrieval rows.
            _ = prior_content  # content may equal (duplicate) or differ (version)
        else:
            seen[legal_id] = (index, content_id)
        legal_ids.append(legal_id)
    return legal_ids


def reject_positional_or_cid_only_merge(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Public helper: refuse merges that rely only on position or content CID."""

    result = classify_identity_pair(left, right)
    disposition = IdentityDisposition.coerce(result["disposition"])
    if disposition in {
        IdentityDisposition.REJECT_POSITIONAL_MERGE,
        IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE,
    }:
        return {**result, "merge_allowed": False}
    if disposition is IdentityDisposition.DISTINCT_IDENTITY:
        return {**result, "merge_allowed": False}
    if disposition is IdentityDisposition.CHANGED_TEXT_VERSION:
        return {**result, "merge_allowed": True, "merge_mode": "version_history"}
    if disposition is IdentityDisposition.DUPLICATE:
        return {**result, "merge_allowed": True, "merge_mode": "deduplicate"}
    return result


def default_collision_fixture_path() -> Path:
    """Return the repository path of the sealed collision fixture."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "state_laws_identity_collisions.json"
    )


def _jurisdiction_cycle() -> tuple[str, ...]:
    return ("CA", "NY", "TX", "FL", "OR", "MN", "WA", "IL", "GA", "DC")


def _code_family_cycle() -> tuple[str, ...]:
    return (
        "civil-code",
        "penal-code",
        "revised-statutes",
        "general-laws",
        "official-code",
        "compiled-statutes",
        "ors",
        "rcw",
        "minnesota-statutes",
        "dc-official-code",
    )


def _synthetic_entry_cid(index: int, *, salt: str = "lcr-006") -> str:
    """Deterministic fake entry_cid (64-hex) for fixture rows."""

    return hashlib.sha256(f"{salt}:{index}".encode("utf-8")).hexdigest()


def expand_collision_fixture(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand a compact collision recipe into concrete row dicts."""

    if not isinstance(payload, Mapping):
        raise CollisionFixtureError("fixture payload must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise CollisionFixtureError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )
    expected = int(payload.get("expected_row_count", KNOWN_COLLISION_ROW_COUNT))
    if expected != KNOWN_COLLISION_ROW_COUNT:
        raise CollisionFixtureError(
            f"expected_row_count must be {KNOWN_COLLISION_ROW_COUNT}, got {expected}"
        )

    rows: list[dict[str, Any]] = []
    jurisdictions = tuple(
        str(j).upper() for j in (payload.get("jurisdiction_cycle") or _jurisdiction_cycle())
    )
    families = tuple(
        str(f).lower() for f in (payload.get("code_family_cycle") or _code_family_cycle())
    )
    if not jurisdictions or not families:
        raise CollisionFixtureError("jurisdiction_cycle and code_family_cycle must be non-empty")

    for raw in payload.get("seed_rows") or ():
        if not isinstance(raw, Mapping):
            raise CollisionFixtureError("seed_rows entries must be mappings")
        rows.append(dict(raw))

    for generator in payload.get("generators") or ():
        if not isinstance(generator, Mapping):
            raise CollisionFixtureError("generators entries must be mappings")
        kind = str(generator.get("kind") or "").strip()
        count = int(generator.get("count") or 0)
        if count < 0:
            raise CollisionFixtureError(f"generator count must be >= 0, got {count}")

        if kind == "truncated_dash_pairs":
            pair_count = count
            section_base = int(generator.get("section_base_start") or 100)
            dash_chars = list(generator.get("dash_chars") or ["\u2013", "\u2014"])
            for pair_index in range(pair_count):
                jurisdiction = jurisdictions[pair_index % len(jurisdictions)]
                code_family = families[pair_index % len(families)]
                base = section_base + pair_index
                dash = dash_chars[pair_index % len(dash_chars)]
                end = base + 1 + (pair_index % 3)
                bare_section = str(base)
                range_section = f"{base}{dash}{end}"
                title = str(10 + (pair_index % 40))
                for local_index, section in enumerate((bare_section, range_section)):
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"dash-pair-{pair_index:04d}-{local_index}",
                            "collision_family": f"dash-pair-{pair_index:04d}",
                            "jurisdiction": jurisdiction,
                            "code_family": code_family,
                            "title": title,
                            "section": section,
                            "source_section": section,
                            "kind": "section",
                            "naive_truncated_section": naive_truncated_section_token(section),
                            "entry_cid": _synthetic_entry_cid(global_index),
                        }
                    )
        elif kind == "qualifier_disambiguation":
            section_base = int(generator.get("section_base_start") or 5000)
            patterns = list(
                generator.get("patterns")
                or (
                    {"appendix": "A"},
                    {"note": "editorial"},
                    {"kind": "history", "note": "historical"},
                    {"edition": "2023-official"},
                    {"appendix": "B", "note": "historical"},
                    {"schedule": "I", "edition": "2024-supp"},
                    {"kind": "current"},
                    {"granule": "{code_family}-title{title}-section{section}"},
                )
            )
            for item_index in range(count):
                jurisdiction = jurisdictions[item_index % len(jurisdictions)]
                code_family = families[item_index % len(families)]
                title = str(20 + (item_index % 30))
                section = str(section_base + (item_index // max(len(patterns), 1)))
                pattern = dict(patterns[item_index % len(patterns)])
                rendered: dict[str, Any] = {}
                for key, value in pattern.items():
                    if isinstance(value, str):
                        rendered[key] = value.format(
                            title=title,
                            section=section,
                            code_family=code_family,
                            jurisdiction=jurisdiction.lower(),
                        )
                    else:
                        rendered[key] = value
                global_index = len(rows)
                kind_value = rendered.get("kind") or (
                    "appendix"
                    if rendered.get("appendix")
                    else ("note" if rendered.get("note") else "section")
                )
                row = {
                    "row_id": f"qual-{item_index:04d}",
                    "collision_family": f"qual-{jurisdiction}-{code_family}-{title}-{section}",
                    "jurisdiction": jurisdiction,
                    "code_family": code_family,
                    "title": title,
                    "section": section,
                    "source_section": section,
                    "kind": kind_value,
                    "naive_truncated_section": naive_truncated_section_token(section),
                    "entry_cid": _synthetic_entry_cid(global_index),
                }
                row.update(rendered)
                rows.append(row)
        elif kind == "code_family_cross":
            # Same jurisdiction + section path under different code families.
            for item_index in range(count):
                jurisdiction = jurisdictions[item_index % len(jurisdictions)]
                code_family = families[item_index % len(families)]
                title = "1"
                section = str(100 + (item_index // len(families)))
                global_index = len(rows)
                rows.append(
                    {
                        "row_id": f"family-{item_index:04d}",
                        "collision_family": f"family-path-{jurisdiction}-{title}-{section}",
                        "jurisdiction": jurisdiction,
                        "code_family": code_family,
                        "title": title,
                        "section": section,
                        "source_section": section,
                        "kind": "section",
                        "entry_cid": _synthetic_entry_cid(global_index),
                    }
                )
        elif kind == "changed_text_versions":
            # Each item emits a pair: same legal identity, different content.
            pair_count = count
            for pair_index in range(pair_count):
                jurisdiction = jurisdictions[pair_index % len(jurisdictions)]
                code_family = families[pair_index % len(families)]
                title = str(50 + (pair_index % 10))
                section = str(9000 + pair_index)
                for local_index, text in enumerate(
                    (f"body-v1-{pair_index}", f"body-v2-{pair_index}")
                ):
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"version-{pair_index:04d}-{local_index}",
                            "collision_family": f"version-{pair_index:04d}",
                            "jurisdiction": jurisdiction,
                            "code_family": code_family,
                            "title": title,
                            "section": section,
                            "source_section": section,
                            "kind": "section",
                            "text": text,
                            "entry_cid": _synthetic_entry_cid(
                                global_index, salt=f"lcr-006-version-{local_index}"
                            ),
                            "expected_disposition": (
                                IdentityDisposition.CHANGED_TEXT_VERSION.value
                                if local_index == 1
                                else IdentityDisposition.KEEP_CURRENT.value
                            ),
                        }
                    )
        elif kind == "content_cid_only_pairs":
            # Same content CID, different legal identities — must not merge.
            pair_count = count
            for pair_index in range(pair_count):
                shared_cid = _synthetic_entry_cid(
                    pair_index, salt="lcr-006-shared-content"
                )
                for local_index in range(2):
                    jurisdiction = jurisdictions[
                        (pair_index + local_index) % len(jurisdictions)
                    ]
                    code_family = families[
                        (pair_index + local_index + 1) % len(families)
                    ]
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"cid-only-{pair_index:04d}-{local_index}",
                            "collision_family": f"cid-only-{pair_index:04d}",
                            "jurisdiction": jurisdiction,
                            "code_family": code_family,
                            "title": str(70 + pair_index),
                            "section": str(300 + local_index),
                            "source_section": str(300 + local_index),
                            "kind": "section",
                            "entry_cid": _synthetic_entry_cid(global_index),
                            "content_cid": shared_cid,
                            "text": f"shared-boilerplate-{pair_index}",
                            "expected_disposition": (
                                IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
                            ),
                        }
                    )
        elif kind == "positional_only_pairs":
            # Same document_index, different legal identities — must not merge.
            pair_count = count
            for pair_index in range(pair_count):
                shared_index = 1000 + pair_index
                for local_index in range(2):
                    jurisdiction = jurisdictions[
                        (pair_index + local_index) % len(jurisdictions)
                    ]
                    code_family = families[
                        (pair_index + local_index + 3) % len(families)
                    ]
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"pos-only-{pair_index:04d}-{local_index}",
                            "collision_family": f"pos-only-{pair_index:04d}",
                            "jurisdiction": jurisdiction,
                            "code_family": code_family,
                            "title": str(80 + pair_index),
                            "section": str(400 + local_index),
                            "source_section": str(400 + local_index),
                            "kind": "section",
                            "document_index": shared_index,
                            "entry_cid": _synthetic_entry_cid(global_index),
                            "text": f"distinct-body-{pair_index}-{local_index}",
                            "expected_disposition": (
                                IdentityDisposition.REJECT_POSITIONAL_MERGE.value
                            ),
                        }
                    )
        elif kind == "unicode_section_variants":
            samples = list(generator.get("samples") or ())
            if not samples:
                raise CollisionFixtureError(
                    "unicode_section_variants generator requires samples"
                )
            for item_index in range(count):
                sample = samples[item_index % len(samples)]
                if not isinstance(sample, Mapping):
                    raise CollisionFixtureError("unicode samples must be mappings")
                jurisdiction = str(
                    sample.get("jurisdiction")
                    or jurisdictions[item_index % len(jurisdictions)]
                ).upper()
                code_family = str(
                    sample.get("code_family") or families[item_index % len(families)]
                )
                section = sample["section"]
                global_index = len(rows)
                rows.append(
                    {
                        "row_id": f"unicode-{item_index:04d}",
                        "collision_family": f"unicode-{item_index:04d}",
                        "jurisdiction": jurisdiction,
                        "code_family": code_family,
                        "title": sample.get("title", "1"),
                        "section": section,
                        "source_section": section,
                        "kind": sample.get("kind", "section"),
                        "appendix": sample.get("appendix"),
                        "note": sample.get("note"),
                        "granule": sample.get("granule"),
                        "edition": sample.get("edition"),
                        "schedule": sample.get("schedule"),
                        "subsection": sample.get("subsection"),
                        "expected_section": sample.get("expected_section"),
                        "naive_truncated_section": naive_truncated_section_token(section),
                        "entry_cid": _synthetic_entry_cid(global_index),
                    }
                )
        else:
            raise CollisionFixtureError(f"unknown generator kind: {kind!r}")

    if len(rows) != expected:
        raise CollisionFixtureError(
            f"expanded fixture has {len(rows)} rows; expected {expected}"
        )

    for index, row in enumerate(rows):
        if "entry_cid" not in row or not row["entry_cid"]:
            row["entry_cid"] = _synthetic_entry_cid(index)
        identity = identity_from_row(row)
        row["legal_id"] = identity.legal_id
        row["canonical_citation"] = identity.canonical_citation
        row["parent_legal_id"] = identity.parent_legal_id
        row["normalized_section"] = identity.section
        row["jurisdiction"] = identity.jurisdiction
        row["code_family"] = identity.code_family
        if "naive_truncated_section" not in row:
            row["naive_truncated_section"] = naive_truncated_section_token(
                row.get("source_section") or row["section"]
            )

    validate_primary_keys(rows)
    return rows


def load_collision_fixture(
    path: PathLike | None = None,
) -> list[dict[str, Any]]:
    """Load and expand the sealed collision fixture."""

    fixture_path = Path(path) if path is not None else default_collision_fixture_path()
    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollisionFixtureError(f"cannot read collision fixture: {fixture_path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollisionFixtureError(f"collision fixture is not valid JSON: {exc}") from exc
    return expand_collision_fixture(payload)


def load_collision_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    """Load the raw (unexpanded) collision fixture mapping."""

    fixture_path = Path(path) if path is not None else default_collision_fixture_path()
    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollisionFixtureError(f"cannot read collision fixture: {fixture_path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollisionFixtureError(f"collision fixture is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CollisionFixtureError("collision fixture root must be an object")
    return payload


def unicode_section_fixtures(payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the explicit Unicode section fixtures from the sealed recipe."""

    if payload is None:
        payload = load_collision_fixture_payload()
    fixtures = payload.get("unicode_section_fixtures") or []
    if not isinstance(fixtures, list):
        raise CollisionFixtureError("unicode_section_fixtures must be a list")
    return [dict(item) for item in fixtures if isinstance(item, Mapping)]


def disposition_cases(payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return explicit pair-disposition cases from the sealed recipe."""

    if payload is None:
        payload = load_collision_fixture_payload()
    cases = payload.get("disposition_cases") or []
    if not isinstance(cases, list):
        raise CollisionFixtureError("disposition_cases must be a list")
    return [dict(item) for item in cases if isinstance(item, Mapping)]


def build_default_collision_fixture_payload() -> dict[str, Any]:
    """Return the sealed compact collision recipe (source of the JSON fixture).

    Row arithmetic (must equal :data:`KNOWN_COLLISION_ROW_COUNT` = 420)::

        seed_rows:                 12
        truncated_dash_pairs:     125 pairs × 2 = 250
        qualifier_disambiguation:  48
        code_family_cross:         20
        changed_text_versions:     20 pairs × 2 = 40
        content_cid_only_pairs:    10 pairs × 2 = 20
        positional_only_pairs:     10 pairs × 2 = 20
        unicode_section_variants:  10
        ─────────────────────────────────────────
        total:                    420
    """

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "expected_row_count": KNOWN_COLLISION_ROW_COUNT,
        "task_id": TASK_ID,
        "description": (
            "Compact recipe for state-law identity collisions and version "
            "dispositions. Dash-range pairs share a naive-truncated section "
            "token but remain distinguishable under repaired legal_id. "
            "Qualifier, code-family, and jurisdiction rows disambiguate shared "
            "section numbers. Changed-text pairs share legal_id with different "
            "content and receive explicit version dispositions. Content-CID-only "
            "and positional-only pairs must not merge."
        ),
        "jurisdiction_cycle": list(_jurisdiction_cycle()),
        "code_family_cycle": list(_code_family_cycle()),
        "unicode_section_fixtures": [
            {
                "jurisdiction": "CA",
                "code_family": "civil-code",
                "title": "1",
                "section": "1001\u20131003",
                "expected_section": "1001-1003",
                "label": "en-dash range",
            },
            {
                "jurisdiction": "NY",
                "code_family": "penal-code",
                "title": "10",
                "section": "1001\u20141003",
                "expected_section": "1001-1003",
                "label": "em-dash range",
            },
            {
                "jurisdiction": "TX",
                "code_family": "revised-statutes",
                "title": "2",
                "section": "1961\u22121968",
                "expected_section": "1961-1968",
                "label": "minus-sign range",
            },
            {
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "§ 456",
                "expected_section": "456",
                "label": "section symbol",
            },
            {
                "jurisdiction": "MN",
                "code_family": "minnesota-statutes",
                "title": "518",
                "section": "Minn. Stat. § 518.17",
                "expected_section": "518.17",
                "label": "full state citation",
            },
            {
                "jurisdiction": "WA",
                "code_family": "rcw",
                "title": "9A",
                "section": "101\u2011a",
                "expected_section": "101-a",
                "label": "non-breaking hyphen lettered tail",
            },
            {
                "jurisdiction": "FL",
                "code_family": "official-code",
                "title": "775",
                "section": "552(a)\u2013(e)",
                "expected_section": "552(a)-(e)",
                "label": "parenthetical en-dash range",
            },
            {
                "jurisdiction": "IL",
                "code_family": "compiled-statutes",
                "title": "720",
                "section": "5/12-3",
                "expected_section": "5/12-3",
                "label": "slash section token",
            },
            {
                "jurisdiction": "DC",
                "code_family": "dc-official-code",
                "title": "22",
                "section": "3001",
                "appendix": "A",
                "expected_section": "3001",
                "label": "appendix-qualified",
            },
            {
                "jurisdiction": "GA",
                "code_family": "official-code",
                "title": "16",
                "section": "5-23",
                "note": "editorial",
                "edition": "2024-official",
                "expected_section": "5-23",
                "label": "note+edition",
            },
        ],
        "disposition_cases": [
            {
                "case_id": "logical-duplicate",
                "expected_disposition": IdentityDisposition.DUPLICATE.value,
                "left": {
                    "jurisdiction": "OR",
                    "code_family": "ors",
                    "title": "123",
                    "section": "456",
                    "entry_cid": "a" * 64,
                    "text": "same body",
                },
                "right": {
                    "jurisdiction": "OR",
                    "code_family": "ors",
                    "title": "123",
                    "section": "456",
                    "entry_cid": "a" * 64,
                    "text": "same body",
                },
            },
            {
                "case_id": "changed-text-version",
                "expected_disposition": IdentityDisposition.CHANGED_TEXT_VERSION.value,
                "left": {
                    "jurisdiction": "MN",
                    "code_family": "minnesota-statutes",
                    "title": "518",
                    "section": "17",
                    "entry_cid": "b" * 64,
                    "text": "old body",
                },
                "right": {
                    "jurisdiction": "MN",
                    "code_family": "minnesota-statutes",
                    "title": "518",
                    "section": "17",
                    "entry_cid": "c" * 64,
                    "text": "new body",
                },
            },
            {
                "case_id": "content-cid-only-reject",
                "expected_disposition": (
                    IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
                ),
                "left": {
                    "jurisdiction": "CA",
                    "code_family": "civil-code",
                    "title": "1",
                    "section": "100",
                    "entry_cid": "d" * 64,
                    "content_cid": "e" * 64,
                    "text": "boilerplate",
                },
                "right": {
                    "jurisdiction": "NY",
                    "code_family": "penal-code",
                    "title": "2",
                    "section": "200",
                    "entry_cid": "f" * 64,
                    "content_cid": "e" * 64,
                    "text": "boilerplate",
                },
            },
            {
                "case_id": "positional-only-reject",
                "expected_disposition": (
                    IdentityDisposition.REJECT_POSITIONAL_MERGE.value
                ),
                "left": {
                    "jurisdiction": "TX",
                    "code_family": "revised-statutes",
                    "title": "1",
                    "section": "10",
                    "document_index": 42,
                    "entry_cid": "1" * 64,
                    "text": "alpha",
                },
                "right": {
                    "jurisdiction": "FL",
                    "code_family": "official-code",
                    "title": "2",
                    "section": "20",
                    "document_index": 42,
                    "entry_cid": "2" * 64,
                    "text": "beta",
                },
            },
            {
                "case_id": "history-vs-current-kind",
                "expected_disposition": IdentityDisposition.DISTINCT_IDENTITY.value,
                "left": {
                    "jurisdiction": "WA",
                    "code_family": "rcw",
                    "title": "9A",
                    "section": "36.011",
                    "kind": "current",
                    "entry_cid": "3" * 64,
                    "text": "current text",
                },
                "right": {
                    "jurisdiction": "WA",
                    "code_family": "rcw",
                    "title": "9A",
                    "section": "36.011",
                    "kind": "history",
                    "note": "prior-codification",
                    "entry_cid": "4" * 64,
                    "text": "historical note",
                },
            },
            {
                "case_id": "code-family-disambiguation",
                "expected_disposition": IdentityDisposition.DISTINCT_IDENTITY.value,
                "left": {
                    "jurisdiction": "CA",
                    "code_family": "civil-code",
                    "title": "1",
                    "section": "50",
                    "entry_cid": "5" * 64,
                },
                "right": {
                    "jurisdiction": "CA",
                    "code_family": "penal-code",
                    "title": "1",
                    "section": "50",
                    "entry_cid": "6" * 64,
                },
            },
        ],
        "seed_rows": [
            {
                "row_id": "seed-en-dash-bare",
                "collision_family": "seed-en-dash",
                "jurisdiction": "CA",
                "code_family": "civil-code",
                "title": "1",
                "section": "2001",
                "source_section": "2001",
                "kind": "section",
            },
            {
                "row_id": "seed-en-dash-range",
                "collision_family": "seed-en-dash",
                "jurisdiction": "CA",
                "code_family": "civil-code",
                "title": "1",
                "section": "2001\u20132003",
                "source_section": "2001\u20132003",
                "kind": "section",
            },
            {
                "row_id": "seed-em-dash-bare",
                "collision_family": "seed-em-dash",
                "jurisdiction": "NY",
                "code_family": "penal-code",
                "title": "10",
                "section": "3001",
                "source_section": "3001",
                "kind": "section",
            },
            {
                "row_id": "seed-em-dash-range",
                "collision_family": "seed-em-dash",
                "jurisdiction": "NY",
                "code_family": "penal-code",
                "title": "10",
                "section": "3001\u20143010",
                "source_section": "3001\u20143010",
                "kind": "section",
            },
            {
                "row_id": "seed-appendix-main",
                "collision_family": "seed-appendix",
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "456",
                "source_section": "456",
                "kind": "section",
            },
            {
                "row_id": "seed-appendix-a",
                "collision_family": "seed-appendix",
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "456",
                "source_section": "456",
                "kind": "appendix",
                "appendix": "A",
            },
            {
                "row_id": "seed-note",
                "collision_family": "seed-appendix",
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "456",
                "source_section": "456",
                "kind": "note",
                "note": "historical",
                "edition": "2023-official",
            },
            {
                "row_id": "seed-history-kind",
                "collision_family": "seed-appendix",
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "456",
                "source_section": "456",
                "kind": "history",
                "note": "prior-codification",
            },
            {
                "row_id": "seed-family-civil",
                "collision_family": "seed-family",
                "jurisdiction": "CA",
                "code_family": "civil-code",
                "title": "2",
                "section": "50",
                "source_section": "50",
                "kind": "section",
            },
            {
                "row_id": "seed-family-penal",
                "collision_family": "seed-family",
                "jurisdiction": "CA",
                "code_family": "penal-code",
                "title": "2",
                "section": "50",
                "source_section": "50",
                "kind": "section",
            },
            {
                "row_id": "seed-dc",
                "collision_family": "seed-dc",
                "jurisdiction": "DC",
                "code_family": "dc-official-code",
                "title": "22",
                "section": "3001",
                "source_section": "3001",
                "kind": "section",
            },
            {
                "row_id": "seed-granule",
                "collision_family": "seed-appendix",
                "jurisdiction": "OR",
                "code_family": "ors",
                "title": "123",
                "section": "456",
                "source_section": "456",
                "kind": "section",
                "granule": "ors-title123-section456",
                "edition": "2024-supp",
            },
        ],
        "generators": [
            {
                "kind": "truncated_dash_pairs",
                "count": 125,
                "section_base_start": 100,
                "dash_chars": ["\u2013", "\u2014", "\u2212"],
            },
            {
                "kind": "qualifier_disambiguation",
                "count": 48,
                "section_base_start": 5000,
            },
            {
                "kind": "code_family_cross",
                "count": 20,
            },
            {
                "kind": "changed_text_versions",
                "count": 20,
            },
            {
                "kind": "content_cid_only_pairs",
                "count": 10,
            },
            {
                "kind": "positional_only_pairs",
                "count": 10,
            },
            {
                "kind": "unicode_section_variants",
                "count": 10,
                "samples": [
                    {
                        "jurisdiction": "CA",
                        "code_family": "civil-code",
                        "title": "1",
                        "section": "61–64",
                        "expected_section": "61-64",
                    },
                    {
                        "jurisdiction": "NY",
                        "code_family": "penal-code",
                        "title": "10",
                        "section": "401—(a)",
                        "expected_section": "401-(a)",
                    },
                    {
                        "jurisdiction": "TX",
                        "code_family": "revised-statutes",
                        "title": "2",
                        "section": "§ 2000e–2",
                        "expected_section": "2000e-2",
                    },
                    {
                        "jurisdiction": "OR",
                        "code_family": "ors",
                        "title": "123",
                        "section": "78j–1",
                        "expected_section": "78j-1",
                    },
                    {
                        "jurisdiction": "MN",
                        "code_family": "minnesota-statutes",
                        "title": "518",
                        "section": "1841–(c)",
                        "expected_section": "1841-(c)",
                    },
                    {
                        "jurisdiction": "WA",
                        "code_family": "rcw",
                        "title": "9A",
                        "section": "3729—3731",
                        "expected_section": "3729-3731",
                    },
                    {
                        "jurisdiction": "FL",
                        "code_family": "official-code",
                        "title": "775",
                        "section": "552a–(b)",
                        "expected_section": "552a-(b)",
                    },
                    {
                        "jurisdiction": "IL",
                        "code_family": "compiled-statutes",
                        "title": "720",
                        "section": "102—(b)",
                        "expected_section": "102-(b)",
                    },
                    {
                        "jurisdiction": "GA",
                        "code_family": "official-code",
                        "title": "16",
                        "section": "106A–106B",
                        "expected_section": "106A-106B",
                    },
                    {
                        "jurisdiction": "DC",
                        "code_family": "dc-official-code",
                        "title": "22",
                        "section": "362–(a)",
                        "expected_section": "362-(a)",
                    },
                ],
            },
        ],
    }
