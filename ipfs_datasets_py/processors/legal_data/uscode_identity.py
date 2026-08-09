"""Canonical U.S. Code section and edition identity (USCIR-006).

This module owns the file-disjoint identity parser/normalizer used by the
``publicus-ir-graphrag/v2`` US Code release. It deliberately does **not**
depend on network I/O, Parquet, or the legacy scraper entry point.

Design invariants
-----------------
* ``legal_id`` is a stable citation-oriented identifier, independent of
  content version (``entry_cid``) and release-local row index.
* ``entry_cid`` is the primary key for retrieval rows; duplicates fail closed.
* Duplicate ``(title, section)`` values are **not** collapsed. Appendix, note,
  granule, edition, subsection, and kind participate in ``legal_id``.
* Unicode en/em dashes (and related dash characters) never truncate section
  tokens. Dash-range sections such as ``1001–1003`` remain fully addressable
  and stay distinguishable from bare ``1001``.
* Chunk parent identity is deterministic and derived from the parent section
  identity (not from positional embedding row numbers).

The sealed collision fixture expands to the 1,798 known truncated-ID
collision rows that a naive ASCII-only parser would collapse.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

SCHEMA_VERSION = "uscode-identity-v1"
FIXTURE_SCHEMA_VERSION = "uscode-identity-collisions-v1"

# Exact count of known truncated-ID collision rows in the sealed fixture.
KNOWN_TRUNCATED_COLLISION_COUNT = 1798

DEFAULT_JURISDICTION = "US"
DEFAULT_KIND = "section"

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

# Section token: numeric base, optional lettered/dotted tails, optional
# parentheticals, and ASCII hyphen ranges after dash normalization.
_SECTION_CORE = r"\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*"
_SECTION_TOKEN_RE = re.compile(
    rf"(?:§+\s*)?(?:sec(?:tion)?\.?\s*)?(?P<section>{_SECTION_CORE}(?:\s*-\s*{_SECTION_CORE})*)",
    re.IGNORECASE,
)
_CITATION_RE = re.compile(
    r"""
    ^\s*
    (?P<title>\d+[A-Za-z]?)\s*
    (?:U\.?\s*S\.?\s*C\.?|USC)\s*
    (?:§+\s*)?
    (?P<section>.+?)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_LEADING_ZEROS_RE = re.compile(r"^0*(\d+)(.*)$")
_CHUNK_SUFFIX_RE = re.compile(r"#chunk=(?P<index>\d+)$")

# Qualifier keys that participate in legal_id construction (sorted for
# deterministic serialization).
_QUALIFIER_KEYS = (
    "appendix",
    "edition",
    "granule",
    "kind",
    "note",
    "schedule",
    "subsection",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


class UscodeIdentityError(ValueError):
    """Base error for U.S. Code identity failures."""


class IdentityParseError(UscodeIdentityError):
    """Raised when a section or citation token cannot be parsed fully."""


class DuplicatePrimaryKeyError(UscodeIdentityError):
    """Raised when duplicate primary keys (``entry_cid``) are detected."""


class CollisionFixtureError(UscodeIdentityError):
    """Raised when the sealed collision fixture is malformed."""


class NodeKind(str, Enum):
    """Structural kind of a legal identity node."""

    SECTION = "section"
    SUBSECTION = "subsection"
    APPENDIX = "appendix"
    NOTE = "note"
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
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        return cls.OTHER


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeIdentityError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise UscodeIdentityError(f"{name} must not contain NUL")
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
        raise UscodeIdentityError("text must be a string")
    # NFKC folds compatibility forms; then map remaining dash code points.
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.translate(_DASH_TRANSLATION)


def normalize_title(title: Any) -> str:
    """Normalize a U.S. Code title number (``\"35\"``, ``\"10a\"``)."""

    text = str(title if title is not None else "").strip()
    if not text:
        raise UscodeIdentityError("title must be non-empty")
    text = normalize_dash_chars(text)
    if text.isdigit():
        return str(int(text))
    return text.lower()


def _normalize_section_core(raw: str) -> str:
    """Normalize one section core token (no surrounding citation noise)."""

    text = normalize_dash_chars(raw).strip()
    text = text.lstrip("§").strip()
    # Drop whitespace around hyphens inside ranges: "1001 - 1003" -> "1001-1003".
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "", text)
    if not text:
        raise IdentityParseError("section must be non-empty")

    # Strip leading zeros on each numeric run while preserving lettered tails
    # and range partners: 0101a-0102b -> 101a-102b.
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

    Accepts bare numbers (``122``), section symbols (``§ 122``), full
    citations (``35 U.S.C. § 122``), lettered tails (``101a``), parenthetical
    subsections on the number (``181(a)``), and dash ranges with ASCII or
    Unicode dashes (``1001–1003``, ``1001—1003``, ``1001-1003``).

    The full range is always preserved. A naive ``\\d+`` or ASCII-only
    ``[A-Za-z0-9.\\-]*`` match that stops before an en-dash is rejected as a
    truncated parse when residual non-noise characters remain.
    """

    if section is None:
        raise IdentityParseError("section must be non-empty")
    original = str(section).strip()
    if not original:
        raise IdentityParseError("section must be non-empty")

    # Prefer an explicit U.S.C. citation shape when present.
    citation = _CITATION_RE.match(original)
    if citation:
        return _normalize_section_core(citation.group("section"))

    dashed = normalize_dash_chars(original)
    candidates = list(_SECTION_TOKEN_RE.finditer(dashed))
    if not candidates:
        # Fall back to the whole string after dash normalization.
        return _normalize_section_core(dashed)

    match = candidates[-1]
    token = match.group("section")
    # Fail closed on truncation: anything after the match (other than trailing
    # citation noise) means the pattern did not consume the full section.
    trailing = dashed[match.end() :].strip()
    trailing = re.sub(r"^[.,;:)\]]+", "", trailing).strip()
    if trailing and not re.fullmatch(r"(?:et\s+seq\.?|note|notes|nn?\.?)?", trailing, re.I):
        # Residual content after a partial match — parse the whole remainder
        # starting at the section rather than silently truncating.
        remainder = dashed[match.start() :]
        # Strip leading "section"/"§" labels from the remainder.
        remainder = re.sub(
            r"^(?:§+\s*|sec(?:tion)?\.?\s*)+",
            "",
            remainder,
            flags=re.IGNORECASE,
        )
        return _normalize_section_core(remainder)

    return _normalize_section_core(token)


def normalize_jurisdiction(jurisdiction: Any = DEFAULT_JURISDICTION) -> str:
    text = _require_non_empty_str(
        jurisdiction if jurisdiction is not None else DEFAULT_JURISDICTION,
        "jurisdiction",
    )
    return text.lower()


def _normalize_qualifier(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    text = _require_non_empty_str(value, name)
    text = normalize_dash_chars(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Qualifiers are case-folded for identity stability.
    return text.lower()


def _format_qualifiers(components: Mapping[str, Optional[str]]) -> str:
    parts: list[str] = []
    for key in _QUALIFIER_KEYS:
        value = components.get(key)
        if value is None or value == "":
            continue
        # Default kind "section" is omitted so simple identities stay compact.
        if key == "kind" and value == DEFAULT_KIND:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return ";" + ";".join(parts)


@dataclass(frozen=True, slots=True)
class LegalIdentity:
    """Canonical legal identity for one U.S. Code addressable unit.

    ``legal_id`` is citation-oriented and independent of content version.
    ``entry_cid`` (when present on a row) is the retrieval primary key and is
    intentionally **not** part of this record.
    """

    title: str
    section: str
    jurisdiction: str = DEFAULT_JURISDICTION
    subsection: Optional[str] = None
    appendix: Optional[str] = None
    note: Optional[str] = None
    granule: Optional[str] = None
    edition: Optional[str] = None
    schedule: Optional[str] = None
    kind: str = DEFAULT_KIND
    chapter: Optional[str] = None
    source_section: Optional[str] = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "jurisdiction", normalize_jurisdiction(self.jurisdiction))
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        object.__setattr__(self, "subsection", _normalize_qualifier(self.subsection, "subsection"))
        object.__setattr__(self, "appendix", _normalize_qualifier(self.appendix, "appendix"))
        object.__setattr__(self, "note", _normalize_qualifier(self.note, "note"))
        object.__setattr__(self, "granule", _normalize_qualifier(self.granule, "granule"))
        object.__setattr__(self, "edition", _normalize_qualifier(self.edition, "edition"))
        object.__setattr__(self, "schedule", _normalize_qualifier(self.schedule, "schedule"))
        kind = NodeKind.coerce(self.kind).value
        object.__setattr__(self, "kind", kind)
        if self.chapter is not None:
            object.__setattr__(self, "chapter", _normalize_qualifier(self.chapter, "chapter"))
        if self.source_section is not None:
            object.__setattr__(
                self,
                "source_section",
                str(self.source_section),
            )

    @property
    def legal_id(self) -> str:
        """Return the stable citation-oriented legal identifier."""

        base = f"usc:{self.jurisdiction}:{self.title}:{self.section}"
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
        """Return Bluebook-style canonical citation text."""

        section_display = self.section
        if self.subsection and f"({self.subsection})" not in section_display:
            # subsection may already be embedded (e.g. 122(a)); only append
            # when it is a bare label.
            if re.fullmatch(r"[a-z0-9]+", self.subsection):
                section_display = f"{section_display}({self.subsection})"
        cite = f"{self.title} U.S.C. § {section_display}"
        extras: list[str] = []
        if self.appendix:
            extras.append(f"app. {self.appendix}")
        if self.schedule:
            extras.append(f"sched. {self.schedule}")
        if self.note:
            extras.append(f"note ({self.note})")
        if self.edition:
            extras.append(f"[{self.edition}]")
        if extras:
            cite = f"{cite} ({', '.join(extras)})"
        return cite

    @property
    def parent_legal_id(self) -> str:
        """Return the deterministic chunk-parent identity.

        Chunks of a section share this parent identity. Subsection-scoped
        identities parent to the bare section (qualifiers preserved).
        """

        if self.subsection is None and self.kind != NodeKind.SUBSECTION.value:
            return self.legal_id
        parent = LegalIdentity(
            title=self.title,
            section=self.section,
            jurisdiction=self.jurisdiction,
            subsection=None,
            appendix=self.appendix,
            note=self.note,
            granule=self.granule,
            edition=self.edition,
            schedule=self.schedule,
            kind=DEFAULT_KIND if self.kind == NodeKind.SUBSECTION.value else self.kind,
            chapter=self.chapter,
        )
        return parent.legal_id

    def chunk_id(self, chunk_index: int) -> str:
        """Return a deterministic chunk identity under this parent."""

        if not isinstance(chunk_index, int) or chunk_index < 0:
            raise UscodeIdentityError("chunk_index must be a non-negative integer")
        return f"{self.parent_legal_id}#chunk={chunk_index:04d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "appendix": self.appendix,
            "canonical_citation": self.canonical_citation,
            "chapter": self.chapter,
            "edition": self.edition,
            "granule": self.granule,
            "jurisdiction": self.jurisdiction,
            "kind": self.kind,
            "legal_id": self.legal_id,
            "note": self.note,
            "parent_legal_id": self.parent_legal_id,
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
            raise UscodeIdentityError("identity payload must be a mapping")
        section = value.get("section")
        if section is None:
            section = value.get("section_number")
        title = value.get("title")
        if title is None:
            title = value.get("title_number")
        source_section = value.get("source_section")
        if source_section is None and section is not None:
            source_section = str(section)
        return cls(
            title=title,
            section=section,
            jurisdiction=value.get("jurisdiction", DEFAULT_JURISDICTION),
            subsection=value.get("subsection"),
            appendix=value.get("appendix"),
            note=value.get("note"),
            granule=value.get("granule") or value.get("granule_id"),
            edition=value.get("edition") or value.get("edition_id"),
            schedule=value.get("schedule"),
            kind=value.get("kind", DEFAULT_KIND),
            chapter=value.get("chapter"),
            source_section=source_section,
        )


def build_legal_id(
    *,
    title: Any,
    section: Any,
    jurisdiction: Any = DEFAULT_JURISDICTION,
    subsection: Any = None,
    appendix: Any = None,
    note: Any = None,
    granule: Any = None,
    edition: Any = None,
    schedule: Any = None,
    kind: Any = DEFAULT_KIND,
    chapter: Any = None,
) -> str:
    """Build a stable ``legal_id`` from citation components."""

    return LegalIdentity(
        title=title,
        section=section,
        jurisdiction=jurisdiction,
        subsection=subsection,
        appendix=appendix,
        note=note,
        granule=granule,
        edition=edition,
        schedule=schedule,
        kind=kind,
        chapter=chapter,
    ).legal_id


def build_canonical_citation(
    *,
    title: Any,
    section: Any,
    subsection: Any = None,
    appendix: Any = None,
    note: Any = None,
    edition: Any = None,
    schedule: Any = None,
    **kwargs: Any,
) -> str:
    """Build Bluebook-style canonical citation text."""

    return LegalIdentity(
        title=title,
        section=section,
        subsection=subsection,
        appendix=appendix,
        note=note,
        edition=edition,
        schedule=schedule,
        **{k: v for k, v in kwargs.items() if k in {"jurisdiction", "granule", "kind", "chapter"}},
    ).canonical_citation


def build_chunk_parent_id(
    *,
    title: Any,
    section: Any,
    jurisdiction: Any = DEFAULT_JURISDICTION,
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
        title=title,
        section=section,
        jurisdiction=jurisdiction,
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
    if not text.startswith("usc:"):
        raise IdentityParseError(f"legal_id must start with 'usc:': {legal_id!r}")
    body = text[4:]
    # Split qualifiers after the base path.
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
    if len(pieces) != 3:
        raise IdentityParseError(
            f"legal_id base must be jurisdiction:title:section, got {base!r}"
        )
    jurisdiction, title, section = pieces
    return LegalIdentity(
        title=title,
        section=section,
        jurisdiction=jurisdiction,
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

    Stops at the first Unicode dash/minus character (the failure mode that
    produced the 1,798 known collision rows). Not used for production IDs.
    """

    text = str(section if section is not None else "")
    # Truncate at the first Unicode dash/minus character (legacy bug).
    for index, char in enumerate(text):
        if char in _UNICODE_DASH_SET:
            text = text[:index]
            break
    # Then apply a narrow ASCII-only token grab similar to legacy parsers.
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
    """Return ``legal_id`` for a row mapping."""

    return identity_from_row(row).legal_id


def validate_primary_keys(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_field: str = "entry_cid",
) -> None:
    """Fail closed when duplicate primary keys are present.

    The retrieval primary key is ``entry_cid``. Duplicate values raise
    :class:`DuplicatePrimaryKeyError`. Missing keys are also rejected so a
    silent empty-key collision cannot pass validation.
    """

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise UscodeIdentityError(f"row {index} must be a mapping")
        if key_field not in row or row[key_field] in (None, ""):
            raise UscodeIdentityError(
                f"row {index} missing required primary key field {key_field!r}"
            )
        key = str(row[key_field])
        if key_field == "entry_cid":
            # Accept either raw sha256 hex or a CID-looking token; reject blanks.
            if not key.strip():
                raise UscodeIdentityError(f"row {index} has empty {key_field}")
        if key in seen:
            raise DuplicatePrimaryKeyError(
                f"duplicate primary key {key_field}={key!r} at rows "
                f"{seen[key]} and {index}"
            )
        seen[key] = index


def assert_legal_ids_distinguishable(
    rows: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Return legal_ids for *rows*, requiring every id to be unique.

    Raises :class:`UscodeIdentityError` when two rows collapse to the same
    ``legal_id`` (the truncated-ID failure mode under repair).
    """

    legal_ids: list[str] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        legal_id = legal_id_from_row(row)
        if legal_id in seen:
            raise UscodeIdentityError(
                f"legal_id collision for {legal_id!r} at rows "
                f"{seen[legal_id]} and {index}"
            )
        seen[legal_id] = index
        legal_ids.append(legal_id)
    return legal_ids


def default_collision_fixture_path() -> Path:
    """Return the repository path of the sealed collision fixture."""

    # ipfs_datasets_py/processors/legal_data/this_file.py -> repo root
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_identity_collisions.json"
    )


def _title_cycle() -> tuple[str, ...]:
    # Representative titles from the evaluation set, cycled for generators.
    return ("5", "11", "17", "18", "26", "28", "31", "35", "42", "47")


def _synthetic_entry_cid(index: int, *, salt: str = "uscir-006") -> str:
    """Deterministic fake entry_cid (64-hex) for fixture rows."""

    return hashlib.sha256(f"{salt}:{index}".encode("utf-8")).hexdigest()


def expand_collision_fixture(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand a compact collision recipe into concrete row dicts.

    The expanded set always contains exactly
    :data:`KNOWN_TRUNCATED_COLLISION_COUNT` rows when the fixture is well-formed.
    """

    if not isinstance(payload, Mapping):
        raise CollisionFixtureError("fixture payload must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise CollisionFixtureError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )
    expected = int(payload.get("expected_row_count", KNOWN_TRUNCATED_COLLISION_COUNT))
    if expected != KNOWN_TRUNCATED_COLLISION_COUNT:
        raise CollisionFixtureError(
            f"expected_row_count must be {KNOWN_TRUNCATED_COLLISION_COUNT}, got {expected}"
        )

    rows: list[dict[str, Any]] = []

    # Explicit seed rows (small, human-readable Unicode fixtures).
    for raw in payload.get("seed_rows") or ():
        if not isinstance(raw, Mapping):
            raise CollisionFixtureError("seed_rows entries must be mappings")
        row = dict(raw)
        rows.append(row)

    titles = tuple(str(t) for t in (payload.get("title_cycle") or _title_cycle()))
    if not titles:
        raise CollisionFixtureError("title_cycle must be non-empty")

    for generator in payload.get("generators") or ():
        if not isinstance(generator, Mapping):
            raise CollisionFixtureError("generators entries must be mappings")
        kind = str(generator.get("kind") or "").strip()
        count = int(generator.get("count") or 0)
        if count < 0:
            raise CollisionFixtureError(f"generator count must be >= 0, got {count}")
        if kind == "truncated_dash_pairs":
            # Each pair emits two rows that share a naive-truncated section
            # token but differ under the repaired identity.
            pair_count = count
            section_base = int(generator.get("section_base_start") or 100)
            dash_chars = list(generator.get("dash_chars") or ["\u2013", "\u2014"])
            for pair_index in range(pair_count):
                title = titles[pair_index % len(titles)]
                base = section_base + pair_index
                dash = dash_chars[pair_index % len(dash_chars)]
                end = base + 1 + (pair_index % 3)
                bare_section = str(base)
                range_section = f"{base}{dash}{end}"
                for local_index, section in enumerate((bare_section, range_section)):
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"dash-pair-{pair_index:04d}-{local_index}",
                            "collision_family": f"dash-pair-{pair_index:04d}",
                            "title": title,
                            "section": section,
                            "source_section": section,
                            "kind": "section",
                            "naive_truncated_section": naive_truncated_section_token(section),
                            "entry_cid": _synthetic_entry_cid(global_index),
                        }
                    )
        elif kind == "qualifier_disambiguation":
            # Same (title, section) distinguished by appendix/note/granule/edition.
            section_base = int(generator.get("section_base_start") or 5000)
            patterns = list(
                generator.get("patterns")
                or (
                    {"appendix": "A"},
                    {"note": "editorial"},
                    {"granule": "USC-prelim-title{title}-section{section}"},
                    {"edition": "olrc-us-pl-118-45"},
                    {"appendix": "B", "note": "historical"},
                    {"schedule": "I", "edition": "govinfo-2023"},
                )
            )
            for item_index in range(count):
                title = titles[item_index % len(titles)]
                section = str(section_base + (item_index // max(len(patterns), 1)))
                pattern = dict(patterns[item_index % len(patterns)])
                # Format granule templates.
                rendered: dict[str, Any] = {}
                for key, value in pattern.items():
                    if isinstance(value, str):
                        rendered[key] = value.format(title=title, section=section)
                    else:
                        rendered[key] = value
                global_index = len(rows)
                kind_value = "appendix" if rendered.get("appendix") else (
                    "note" if rendered.get("note") else "section"
                )
                row = {
                    "row_id": f"qual-{item_index:04d}",
                    "collision_family": f"qual-section-{title}-{section}",
                    "title": title,
                    "section": section,
                    "source_section": section,
                    "kind": kind_value,
                    "naive_truncated_section": naive_truncated_section_token(section),
                    "entry_cid": _synthetic_entry_cid(global_index),
                }
                row.update(rendered)
                rows.append(row)
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
                title = str(sample.get("title") or titles[item_index % len(titles)])
                section = sample["section"]
                global_index = len(rows)
                rows.append(
                    {
                        "row_id": f"unicode-{item_index:04d}",
                        "collision_family": f"unicode-{item_index:04d}",
                        "title": title,
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

    # Ensure every row has a unique entry_cid and attach repaired legal_id.
    for index, row in enumerate(rows):
        if "entry_cid" not in row or not row["entry_cid"]:
            row["entry_cid"] = _synthetic_entry_cid(index)
        identity = identity_from_row(row)
        row["legal_id"] = identity.legal_id
        row["canonical_citation"] = identity.canonical_citation
        row["parent_legal_id"] = identity.parent_legal_id
        row["normalized_section"] = identity.section
        if "naive_truncated_section" not in row:
            row["naive_truncated_section"] = naive_truncated_section_token(
                row.get("source_section") or row["section"]
            )

    validate_primary_keys(rows)
    assert_legal_ids_distinguishable(rows)
    return rows


def load_collision_fixture(
    path: PathLike | None = None,
) -> list[dict[str, Any]]:
    """Load and expand the sealed truncated-ID collision fixture."""

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


def build_default_collision_fixture_payload() -> dict[str, Any]:
    """Return the sealed compact collision recipe (source of the JSON fixture)."""

    # 860 dash pairs = 1720 rows; 60 qualifier rows; 18 unicode variants;
    # plus seed rows below to reach exactly 1798.
    # seed_rows: 8, unicode generator: 18, qualifier: 60, dash pairs: 856*2=1712
    # 8 + 18 + 60 + 1712 = 1798.
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "expected_row_count": KNOWN_TRUNCATED_COLLISION_COUNT,
        "description": (
            "Compact recipe for the 1,798 known truncated-ID collision rows. "
            "Dash-range pairs share a naive-truncated section token but remain "
            "distinguishable under repaired legal_id construction. Qualifier "
            "rows exercise appendix/note/granule/edition disambiguation. "
            "Unicode fixtures prove en/em dash and related section tokens parse fully."
        ),
        "title_cycle": list(_title_cycle()),
        "unicode_section_fixtures": [
            {
                "title": "26",
                "section": "1001\u20131003",
                "expected_section": "1001-1003",
                "label": "en-dash range",
            },
            {
                "title": "26",
                "section": "1001\u20141003",
                "expected_section": "1001-1003",
                "label": "em-dash range",
            },
            {
                "title": "18",
                "section": "1961\u22121968",
                "expected_section": "1961-1968",
                "label": "minus-sign range",
            },
            {
                "title": "42",
                "section": "§ 1983",
                "expected_section": "1983",
                "label": "section symbol",
            },
            {
                "title": "35",
                "section": "35 U.S.C. § 122",
                "expected_section": "122",
                "label": "full citation",
            },
            {
                "title": "11",
                "section": "101\u2011a",
                "expected_section": "101-a",
                "label": "non-breaking hyphen lettered tail",
            },
            {
                "title": "5",
                "section": "552(a)\u2013(e)",
                "expected_section": "552(a)-(e)",
                "label": "parenthetical en-dash range",
            },
            {
                "title": "28",
                "section": "1331",
                "appendix": "A",
                "expected_section": "1331",
                "label": "appendix-qualified",
            },
            {
                "title": "17",
                "section": "107",
                "note": "editorial",
                "edition": "olrc-us-pl-118-45",
                "expected_section": "107",
                "label": "note+edition",
            },
            {
                "title": "47",
                "section": "230",
                "granule": "USC-prelim-title47-section230",
                "expected_section": "230",
                "label": "granule-qualified",
            },
        ],
        "seed_rows": [
            {
                "row_id": "seed-en-dash-bare",
                "collision_family": "seed-en-dash",
                "title": "26",
                "section": "2001",
                "source_section": "2001",
                "kind": "section",
            },
            {
                "row_id": "seed-en-dash-range",
                "collision_family": "seed-en-dash",
                "title": "26",
                "section": "2001\u20132003",
                "source_section": "2001\u20132003",
                "kind": "section",
            },
            {
                "row_id": "seed-em-dash-bare",
                "collision_family": "seed-em-dash",
                "title": "18",
                "section": "3001",
                "source_section": "3001",
                "kind": "section",
            },
            {
                "row_id": "seed-em-dash-range",
                "collision_family": "seed-em-dash",
                "title": "18",
                "section": "3001\u20143010",
                "source_section": "3001\u20143010",
                "kind": "section",
            },
            {
                "row_id": "seed-appendix-main",
                "collision_family": "seed-appendix",
                "title": "28",
                "section": "1291",
                "source_section": "1291",
                "kind": "section",
            },
            {
                "row_id": "seed-appendix-a",
                "collision_family": "seed-appendix",
                "title": "28",
                "section": "1291",
                "source_section": "1291",
                "kind": "appendix",
                "appendix": "A",
            },
            {
                "row_id": "seed-note",
                "collision_family": "seed-appendix",
                "title": "28",
                "section": "1291",
                "source_section": "1291",
                "kind": "note",
                "note": "historical",
                "edition": "olrc-us-pl-118-45",
            },
            {
                "row_id": "seed-granule",
                "collision_family": "seed-appendix",
                "title": "28",
                "section": "1291",
                "source_section": "1291",
                "kind": "section",
                "granule": "USC-prelim-title28-section1291",
                "edition": "govinfo-2023-title28",
            },
        ],
        "generators": [
            {
                "kind": "truncated_dash_pairs",
                "count": 856,
                "section_base_start": 100,
                "dash_chars": ["\u2013", "\u2014", "\u2212"],
            },
            {
                "kind": "qualifier_disambiguation",
                "count": 60,
                "section_base_start": 5000,
            },
            {
                "kind": "unicode_section_variants",
                "count": 18,
                "samples": [
                    {"title": "26", "section": "61\u201364", "expected_section": "61-64"},
                    {"title": "26", "section": "401\u2014(a)", "expected_section": "401-(a)"},
                    {
                        "title": "42",
                        "section": "§ 2000e\u20132",
                        "expected_section": "2000e-2",
                    },
                    {
                        "title": "15",
                        "section": "78j\u20131",
                        "expected_section": "78j-1",
                    },
                    {
                        "title": "12",
                        "section": "1841\u2013(c)",
                        "expected_section": "1841-(c)",
                    },
                    {
                        "title": "31",
                        "section": "3729\u20143731",
                        "expected_section": "3729-3731",
                    },
                    {
                        "title": "5",
                        "section": "552a\u2013(b)",
                        "expected_section": "552a-(b)",
                    },
                    {
                        "title": "35",
                        "section": "102\u2014(b)",
                        "expected_section": "102-(b)",
                    },
                    {
                        "title": "17",
                        "section": "106A\u2013106B",
                        "expected_section": "106A-106B",
                    },
                    {
                        "title": "11",
                        "section": "362\u2013(a)",
                        "expected_section": "362-(a)",
                    },
                    {
                        "title": "47",
                        "section": "230\u2014(c)",
                        "expected_section": "230-(c)",
                    },
                    {
                        "title": "18",
                        "section": "1030\u2013(a)",
                        "expected_section": "1030-(a)",
                    },
                    {
                        "title": "28",
                        "section": "1332\u2014(a)",
                        "expected_section": "1332-(a)",
                    },
                    {
                        "title": "26",
                        "section": "501\u2013(c)(3)",
                        "expected_section": "501-(c)(3)",
                    },
                    {
                        "title": "42",
                        "section": "12101\u201412117",
                        "expected_section": "12101-12117",
                    },
                    {
                        "title": "5",
                        "section": "701\u2013706",
                        "expected_section": "701-706",
                    },
                    {
                        "title": "35",
                        "section": "271\u2014(e)",
                        "expected_section": "271-(e)",
                    },
                    {
                        "title": "18",
                        "section": "2510\u20132522",
                        "expected_section": "2510-2522",
                    },
                ],
            },
        ],
    }


def write_default_collision_fixture(path: PathLike | None = None) -> Path:
    """Write the sealed compact collision recipe to *path* (or default)."""

    fixture_path = Path(path) if path is not None else default_collision_fixture_path()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_collision_fixture_payload()
    # Validate expansion before writing.
    expand_collision_fixture(payload)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fixture_path.write_text(text, encoding="utf-8")
    return fixture_path


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "KNOWN_TRUNCATED_COLLISION_COUNT",
    "DEFAULT_JURISDICTION",
    "DEFAULT_KIND",
    "UscodeIdentityError",
    "IdentityParseError",
    "DuplicatePrimaryKeyError",
    "CollisionFixtureError",
    "NodeKind",
    "LegalIdentity",
    "normalize_dash_chars",
    "normalize_title",
    "normalize_section_token",
    "normalize_jurisdiction",
    "build_legal_id",
    "build_canonical_citation",
    "build_chunk_parent_id",
    "parse_chunk_id",
    "parse_legal_id",
    "naive_truncated_section_token",
    "identity_from_row",
    "legal_id_from_row",
    "validate_primary_keys",
    "assert_legal_ids_distinguishable",
    "default_collision_fixture_path",
    "expand_collision_fixture",
    "load_collision_fixture",
    "load_collision_fixture_payload",
    "unicode_section_fixtures",
    "build_default_collision_fixture_payload",
    "write_default_collision_fixture",
]
