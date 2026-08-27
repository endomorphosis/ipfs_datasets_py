"""Structure-aware state statute chunking (LCR-025).

This module owns semantic segmentation of admitted state-law text for the
``state-laws-ir-graphrag/v2`` release. It deliberately does **not** perform
physical Parquet sharding and never treats the 4,096-row storage bound as a
model token ceiling.

Design invariants
-----------------
* ``model_token_limit`` is an **explicit required argument**. Callers must
  pass the selected embedding model's maximum input tokens; there is no
  silent default of 4,096.
* Oversized provisions are split on code / title / chapter / section /
  subsection boundaries first, then sentences, then hard token windows.
* Every chunk records stable character and token offsets, a parent path, a
  deterministic chunk identity (via :mod:`state_laws_identity`), and a
  content-addressed chunk CID.
* Exclusive ``(char_start, char_end)`` spans of a statute's chunks cover the
  full source text without gaps or overlaps, enabling exact reconstruction.
  Controlled overlap is carried only in the embeddable ``text`` field.
* Non-exempt chunks never exceed the selected model token limit. The only
  exempt case is a single unsplittable token longer than the limit.
* Huge-section output is bounded by ``max_chunks_per_section``.

Depends on LCR-006 (identity) and LCR-024 (canonical corpus). Physical
sharding belongs to the shared adapter (LCR-026).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data import legal_chunking_core as _chunking_core
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    code_family_for,
    fixture_statute_text,
    parse_hierarchy_unit,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    LegalIdentity,
    build_chunk_parent_id,
    build_legal_id,
    identity_from_row,
    parse_chunk_id,
)

SCHEMA_VERSION = "state-laws-chunker-v1"
FIXTURE_SCHEMA_VERSION = "state-laws-chunk-boundaries-v1"
TASK_ID = "LCR-025"
GOAL_ID = "LCR-G030"
PRODUCER = "state_laws_chunker.py"

# Physical retrieval-unit bound (rows/pointers). Documented only — never used
# as an implicit model token ceiling.
PHYSICAL_ROW_LIMIT = 4096

DEFAULT_OVERLAP_TOKENS = 32
DEFAULT_MAX_CHUNKS_PER_SECTION = 512
DEFAULT_TOKENIZER_ID = "state-laws-whitespace-v1"

# Parenthetical statutory markers: (a), (1), (A), (i), (iv), (I), ...
_SUBSEC_MARKER_RE = re.compile(r"\(([0-9A-Za-z]{1,6})\)")
_ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)

# Line-anchored code / title / chapter / part / article / section headings.
_HIERARCHY_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"(?P<code>(?:THE\s+)?(?P<code_name>"
    r"[A-Z][A-Z.'&\-]{1,40}(?:\s+[A-Z][A-Z.'&\-]{1,40}){0,5}"
    r"\s+(?:CODE|LAW|STATUTES)))"
    r"|(?P<title_kw>TITLE|Tit\.)[ \t]+(?P<title_n>[0-9IVXLCM]+[A-Za-z0-9\-]*)"
    r"|(?P<chapter_kw>CHAPTER|Ch\.)[ \t]+(?P<chapter_n>[0-9IVXLCM]+[A-Za-z0-9\-]*)"
    r"|(?P<part_kw>PART|Pt\.)[ \t]+(?P<part_n>[0-9IVXLCM]+[A-Za-z0-9\-]*)"
    r"|(?P<article_kw>ARTICLE|Art\.)[ \t]+(?P<article_n>[0-9IVXLCM]+[A-Za-z0-9\-]*)"
    r"|(?P<section_kw>SECTION|Sec\.|§+)[ \t]*(?P<section_n>[0-9A-Za-z.\-]+)"
    r")"
)

_COMMON_ROMAN_LOWER = frozenset(
    {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}
)
_COMMON_ROMAN_UPPER = frozenset(s.upper() for s in _COMMON_ROMAN_LOWER)

_HIERARCHY_PATH_KEYS = (
    "jurisdiction",
    "code",
    "title",
    "chapter",
    "part",
    "article",
    "section",
)
_CLEAR_BELOW = {
    "code": ("title", "chapter", "part", "article", "section"),
    "title": ("chapter", "part", "article", "section"),
    "chapter": ("part", "article", "section"),
    "part": ("article", "section"),
    "article": ("section",),
    "section": (),
}

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# Preserve the existing module-level API while binding all corpus-neutral
# mechanics to one implementation shared with the U.S.-Code chunker.
_assert_chunks_within_limit = _chunking_core.assert_chunks_within_limit
_assert_exact_reconstruction = _chunking_core.assert_exact_reconstruction
_normalize_chunk_text = _chunking_core.normalize_chunk_text
_pack_pieces = _chunking_core.pack_pieces
_piece_token_count = _chunking_core.token_count_in_span
_sentence_spans = _chunking_core.sentence_spans
_validate_model_token_limit = _chunking_core.validate_model_token_limit
build_chunk_cid_seed = _chunking_core.build_chunk_cid_seed
canonical_json_bytes = _chunking_core.canonical_json_bytes
chunk_cid_for_payload = _chunking_core.chunk_cid_for_payload
content_sha256 = _chunking_core.content_sha256
hard_token_windows = _chunking_core.hard_token_windows
reconstruct_text = _chunking_core.reconstruct_text
repair_coverage = _chunking_core.repair_coverage
token_index_covering_char = _chunking_core.token_index_covering_char
whitespace_token_rows = _chunking_core.whitespace_token_rows


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsChunkerError(ValueError):
    """Base error for structure-aware state-law chunking failures."""


class ChunkerConfigError(StateLawsChunkerError):
    """Raised when chunking configuration is invalid."""


class ChunkBoundaryFixtureError(StateLawsChunkerError):
    """Raised when the sealed chunk-boundary fixture is malformed."""


class LegalBoundaryError(StateLawsChunkerError):
    """Raised when a chunk splits a legal heading or marker."""


# ---------------------------------------------------------------------------
# Enums / small value types
# ---------------------------------------------------------------------------


class SplitMode(str, Enum):
    """How a chunk's exclusive span was produced."""

    STRUCTURE = "structure"
    SENTENCE = "sentence"
    HARD = "hard"
    WHOLE = "whole"


class UnitKind(str, Enum):
    """Structural unit kind at a marker or heading."""

    PREAMBLE = "preamble"
    CODE = "code"
    TITLE = "title"
    CHAPTER = "chapter"
    PART = "part"
    ARTICLE = "article"
    SECTION = "section"
    SUBSECTION = "subsection"
    PARAGRAPH = "paragraph"
    SUBPARAGRAPH = "subparagraph"
    CLAUSE = "clause"
    SUBCLAUSE = "subclause"
    OTHER = "other"


_HIERARCHY_KIND_TO_KEY = {
    UnitKind.CODE: "code",
    UnitKind.TITLE: "title",
    UnitKind.CHAPTER: "chapter",
    UnitKind.PART: "part",
    UnitKind.ARTICLE: "article",
    UnitKind.SECTION: "section",
}


# ---------------------------------------------------------------------------
# Tokenization (deterministic, locale-independent, no model downloads)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenSpan:
    """One deterministic token with character offsets into source text."""

    index: int
    char_start: int
    char_end: int
    text: str


def normalize_chunk_text(text: str) -> str:
    """NFKC-normalize statutory text without changing caller reconstruction.

    The chunker always normalizes once at entry. Exact reconstruction is
    against that same normalized string.
    """

    return _normalize_chunk_text(text, error_type=StateLawsChunkerError)


def tokenize(text: str) -> list[TokenSpan]:
    """Tokenize *text* with the sealed whitespace tokenizer."""

    return [
        TokenSpan(index=index, char_start=start, char_end=end, text=token_text)
        for index, start, end, token_text in whitespace_token_rows(
            text,
            error_type=StateLawsChunkerError,
        )
    ]


def count_tokens(text: str) -> int:
    """Return the deterministic token count for *text*."""

    return len(tokenize(text))


# ---------------------------------------------------------------------------
# Structural marker detection
# ---------------------------------------------------------------------------


def _slug_heading_token(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or text.strip().lower()


def _classify_parenthetical_kind(token: str, prev_kind: Optional[str]) -> UnitKind:
    if token.isdigit():
        return UnitKind.PARAGRAPH
    if token.islower():
        if token in _COMMON_ROMAN_LOWER and prev_kind in {
            UnitKind.SUBPARAGRAPH.value,
            UnitKind.CLAUSE.value,
            UnitKind.SUBCLAUSE.value,
            "subparagraph",
            "clause",
            "subclause",
        }:
            return UnitKind.CLAUSE
        if len(token) > 1 and _ROMAN_LOWER_RE.match(token):
            return UnitKind.CLAUSE
        return UnitKind.SUBSECTION
    if token.isupper():
        if token in _COMMON_ROMAN_UPPER and prev_kind in {
            UnitKind.CLAUSE.value,
            UnitKind.SUBCLAUSE.value,
            "clause",
            "subclause",
        }:
            return UnitKind.SUBCLAUSE
        if len(token) > 1 and _ROMAN_LOWER_RE.match(token):
            return UnitKind.SUBCLAUSE
        return UnitKind.SUBPARAGRAPH
    return UnitKind.OTHER


def _marker_level(kind: UnitKind) -> int:
    order = {
        UnitKind.PREAMBLE: 0,
        UnitKind.CODE: 1,
        UnitKind.TITLE: 2,
        UnitKind.CHAPTER: 3,
        UnitKind.PART: 4,
        UnitKind.ARTICLE: 5,
        UnitKind.SECTION: 6,
        UnitKind.SUBSECTION: 7,
        UnitKind.PARAGRAPH: 8,
        UnitKind.SUBPARAGRAPH: 9,
        UnitKind.CLAUSE: 10,
        UnitKind.SUBCLAUSE: 11,
        UnitKind.OTHER: 12,
    }
    return order.get(kind, 12)


def find_hierarchy_headings(text: str) -> list[tuple[int, int, str, UnitKind]]:
    """Return line-anchored code/title/chapter/section headings."""

    headings: list[tuple[int, int, str, UnitKind]] = []
    for match in _HIERARCHY_HEADING_RE.finditer(text):
        if match.group("code"):
            token = _slug_heading_token(match.group("code"))
            kind = UnitKind.CODE
        elif match.group("title_kw"):
            token = _slug_heading_token(match.group("title_n"))
            kind = UnitKind.TITLE
        elif match.group("chapter_kw"):
            token = _slug_heading_token(match.group("chapter_n"))
            kind = UnitKind.CHAPTER
        elif match.group("part_kw"):
            token = _slug_heading_token(match.group("part_n"))
            kind = UnitKind.PART
        elif match.group("article_kw"):
            token = _slug_heading_token(match.group("article_n"))
            kind = UnitKind.ARTICLE
        elif match.group("section_kw"):
            token = _slug_heading_token(match.group("section_n"))
            kind = UnitKind.SECTION
        else:
            continue
        headings.append((match.start(), match.end(), token, kind))
    return headings


def find_parenthetical_markers(text: str) -> list[tuple[int, int, str, UnitKind]]:
    """Return ``(start, end, token, kind)`` for statutory parentheticals."""

    markers: list[tuple[int, int, str, UnitKind]] = []
    prev_kind: Optional[str] = None
    for match in _SUBSEC_MARKER_RE.finditer(text):
        start, end = match.start(), match.end()
        token = match.group(1)
        if len(token) > 6:
            continue
        if token.isdigit() and len(token) > 3:
            continue
        if token.isalpha():
            if not (token.islower() or token.isupper()):
                continue
            if len(token) > 1:
                if token.islower() and not _ROMAN_LOWER_RE.match(token):
                    continue
                if token.isupper() and not _ROMAN_LOWER_RE.match(token):
                    continue

        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""
        valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.()[]"
        valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
        if not (valid_left and valid_right):
            continue

        kind = _classify_parenthetical_kind(token, prev_kind)
        prev_kind = kind.value
        markers.append((start, end, token, kind))
    return markers


def find_structural_markers(text: str) -> list[tuple[int, int, str, UnitKind]]:
    """Return merged hierarchy headings and parenthetical markers.

    Markers are ordered by start offset. A parenthetical that overlaps a
    heading is dropped so ``SECTION 552(a)`` still yields the section heading.
    """

    headings = find_hierarchy_headings(text)
    parentheticals = find_parenthetical_markers(text)
    occupied = [(start, end) for start, end, _, _ in headings]
    merged: list[tuple[int, int, str, UnitKind]] = list(headings)
    for start, end, token, kind in parentheticals:
        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied):
            continue
        merged.append((start, end, token, kind))
    merged.sort(key=lambda item: (item[0], item[1], _marker_level(item[3])))
    return merged


def _cursor_from_base_path(base_path: Sequence[str]) -> dict[str, str]:
    cursor: dict[str, str] = {}
    for segment in base_path:
        if not segment or ":" not in str(segment):
            continue
        key, _, value = str(segment).partition(":")
        if key in _HIERARCHY_PATH_KEYS and value:
            cursor[key] = value
    return cursor


def identity_cursor(identity: LegalIdentity) -> dict[str, str]:
    """Return the hierarchy cursor derived from a durable legal identity."""

    cursor: dict[str, str] = {
        "jurisdiction": identity.jurisdiction,
        "code": identity.code_family,
    }
    if identity.title:
        cursor["title"] = identity.title
    if identity.chapter:
        cursor["chapter"] = identity.chapter
    if identity.part:
        cursor["part"] = identity.part
    if identity.article:
        cursor["article"] = identity.article
    if identity.section:
        cursor["section"] = identity.section
    return cursor


def _cursor_path(cursor: Mapping[str, str], extra: Sequence[str] = ()) -> tuple[str, ...]:
    parts: list[str] = []
    for key in _HIERARCHY_PATH_KEYS:
        value = cursor.get(key)
        if value:
            parts.append(f"{key}:{value}")
    parts.extend(extra)
    return tuple(parts)


def _apply_hierarchy_marker(
    cursor: dict[str, str], key: str, token: str
) -> dict[str, str]:
    updated = dict(cursor)
    updated[key] = token
    for deeper in _CLEAR_BELOW.get(key, ()):
        updated.pop(deeper, None)
    return updated


@dataclass(frozen=True, slots=True)
class StructuralUnit:
    """One exclusive structural span of a statute body."""

    label: str
    kind: str
    char_start: int
    char_end: int
    parent_path: tuple[str, ...]
    text: str

    @property
    def token_count(self) -> int:
        return count_tokens(self.text)


def segment_structural_units(
    text: str,
    *,
    base_path: Sequence[str] = (),
    cursor: Mapping[str, str] | None = None,
) -> list[StructuralUnit]:
    """Split *text* into exclusive structural units covering the full string.

    Units include an optional preamble (text before the first marker) and one
    unit per marker span through the next marker. Nested parentheticals are
    retained inside the parent unit's text so deeper packing can re-segment
    if the parent is oversized. Hierarchy headings update a running
    code/title/chapter/section cursor.
    """

    if not text:
        return []

    markers = find_structural_markers(text)
    live_cursor = _cursor_from_base_path(base_path)
    if cursor:
        live_cursor.update({str(k): str(v) for k, v in cursor.items() if v})

    if not markers:
        return [
            StructuralUnit(
                label="body",
                kind=UnitKind.PREAMBLE.value,
                char_start=0,
                char_end=len(text),
                parent_path=_cursor_path(live_cursor, ("body",)),
                text=text,
            )
        ]

    units: list[StructuralUnit] = []
    first_start = markers[0][0]
    if first_start > 0:
        preamble = text[:first_start]
        units.append(
            StructuralUnit(
                label="preamble",
                kind=UnitKind.PREAMBLE.value,
                char_start=0,
                char_end=first_start,
                parent_path=_cursor_path(live_cursor, ("preamble",)),
                text=preamble,
            )
        )

    extra_stack: list[tuple[int, str]] = []
    working = dict(live_cursor)
    for idx, (start, _end, token, kind) in enumerate(markers):
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        hierarchy_key = _HIERARCHY_KIND_TO_KEY.get(kind)
        if hierarchy_key is not None:
            working = _apply_hierarchy_marker(working, hierarchy_key, token)
            extra_stack = []
            path = _cursor_path(working)
            label = f"{kind.value}:{token}"
        else:
            level = _marker_level(kind)
            while extra_stack and extra_stack[-1][0] >= level:
                extra_stack.pop()
            extra_stack.append((level, f"{kind.value}:{token}"))
            path = _cursor_path(working, tuple(seg for _, seg in extra_stack))
            label = f"({token})"
        units.append(
            StructuralUnit(
                label=label,
                kind=kind.value,
                char_start=start,
                char_end=next_start,
                parent_path=path,
                text=text[start:next_start],
            )
        )
    return units


# ---------------------------------------------------------------------------
# Chunk records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalTextChunk:
    """One semantic chunk of a state statute."""

    chunk_index: int
    chunk_id: str
    chunk_cid: str
    parent_legal_id: str
    legal_id: str
    text: str
    exclusive_text: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    token_count: int
    context_char_start: int
    context_token_start: int
    overlap_token_count: int
    parent_path: tuple[str, ...]
    split_mode: str
    limit_exempt: bool = False
    model_token_limit: int = 0
    tokenizer_id: str = DEFAULT_TOKENIZER_ID
    schema_version: str = SCHEMA_VERSION
    jurisdiction: str = ""
    code_family: str = ""
    title: str = ""
    chapter: str = ""
    part: str = ""
    article: str = ""
    section: str = ""
    heading: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_path"] = list(self.parent_path)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalTextChunk":
        if not isinstance(value, Mapping):
            raise StateLawsChunkerError("chunk payload must be a mapping")
        path = value.get("parent_path") or ()
        if isinstance(path, list):
            path = tuple(path)
        return cls(
            chunk_index=int(value["chunk_index"]),
            chunk_id=str(value["chunk_id"]),
            chunk_cid=str(value["chunk_cid"]),
            parent_legal_id=str(value["parent_legal_id"]),
            legal_id=str(value["legal_id"]),
            text=str(value["text"]),
            exclusive_text=str(value["exclusive_text"]),
            char_start=int(value["char_start"]),
            char_end=int(value["char_end"]),
            token_start=int(value["token_start"]),
            token_end=int(value["token_end"]),
            token_count=int(value["token_count"]),
            context_char_start=int(value["context_char_start"]),
            context_token_start=int(value["context_token_start"]),
            overlap_token_count=int(value["overlap_token_count"]),
            parent_path=tuple(path),
            split_mode=str(value["split_mode"]),
            limit_exempt=bool(value.get("limit_exempt", False)),
            model_token_limit=int(value.get("model_token_limit") or 0),
            tokenizer_id=str(value.get("tokenizer_id") or DEFAULT_TOKENIZER_ID),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            jurisdiction=str(value.get("jurisdiction") or ""),
            code_family=str(value.get("code_family") or ""),
            title=str(value.get("title") or ""),
            chapter=str(value.get("chapter") or ""),
            part=str(value.get("part") or ""),
            article=str(value.get("article") or ""),
            section=str(value.get("section") or ""),
            heading=str(value.get("heading") or ""),
        )


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """Result of chunking one statute body."""

    chunks: tuple[LegalTextChunk, ...]
    source_text: str
    source_token_count: int
    model_token_limit: int
    overlap_tokens: int
    max_chunks_per_section: int
    truncated: bool
    tokenizer_id: str = DEFAULT_TOKENIZER_ID
    schema_version: str = SCHEMA_VERSION
    parent_legal_id: str = ""
    legal_id: str = ""
    jurisdiction: str = ""
    code_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_count": len(self.chunks),
            "chunks": [c.to_dict() for c in self.chunks],
            "code_family": self.code_family,
            "jurisdiction": self.jurisdiction,
            "legal_id": self.legal_id,
            "max_chunks_per_section": self.max_chunks_per_section,
            "model_token_limit": self.model_token_limit,
            "overlap_tokens": self.overlap_tokens,
            "parent_legal_id": self.parent_legal_id,
            "schema_version": self.schema_version,
            "source_text": self.source_text,
            "source_token_count": self.source_token_count,
            "tokenizer_id": self.tokenizer_id,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# Content addressing
# ---------------------------------------------------------------------------


def _cid_seed(
    *,
    parent_legal_id: str,
    chunk_index: int,
    exclusive_text: str,
    char_start: int,
    char_end: int,
    token_start: int,
    token_end: int,
    parent_path: Sequence[str],
    split_mode: str,
    tokenizer_id: str,
) -> dict[str, Any]:
    return build_chunk_cid_seed(
        parent_legal_id=parent_legal_id,
        chunk_index=chunk_index,
        exclusive_text=exclusive_text,
        char_start=char_start,
        char_end=char_end,
        token_start=token_start,
        token_end=token_end,
        parent_path=parent_path,
        split_mode=split_mode,
        tokenizer_id=tokenizer_id,
        schema_version=SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# Subdivision helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Piece:
    """Internal exclusive piece before packing into chunks."""

    char_start: int
    char_end: int
    parent_path: tuple[str, ...]
    split_mode: str
    limit_exempt: bool = False


def _hard_token_windows(
    tokens: Sequence[TokenSpan],
    *,
    char_start: int,
    char_end: int,
    model_token_limit: int,
    parent_path: tuple[str, ...],
) -> list[_Piece]:
    """Hard-split the token range covering ``[char_start, char_end)``."""

    return hard_token_windows(
        tokens,
        char_start=char_start,
        char_end=char_end,
        model_token_limit=model_token_limit,
        parent_path=parent_path,
        piece_factory=_Piece,
        hard_split_mode=SplitMode.HARD.value,
        error_type=ChunkerConfigError,
    )


def _subdivide_unit(
    unit: StructuralUnit,
    *,
    source_text: str,
    tokens: Sequence[TokenSpan],
    model_token_limit: int,
    depth: int = 0,
) -> list[_Piece]:
    """Subdivide an oversized structural unit into limit-compliant pieces."""

    unit_tokens = [
        t for t in tokens if t.char_end > unit.char_start and t.char_start < unit.char_end
    ]
    n_tokens = len(unit_tokens)
    if n_tokens <= model_token_limit:
        split_mode = (
            SplitMode.STRUCTURE.value
            if unit.kind != UnitKind.PREAMBLE.value
            else SplitMode.WHOLE.value
        )
        return [
            _Piece(
                char_start=unit.char_start,
                char_end=unit.char_end,
                parent_path=unit.parent_path,
                split_mode=split_mode,
            )
        ]

    if depth < 4:
        inner = unit.text
        inner_markers = [m for m in find_structural_markers(inner) if m[0] > 0]
        if inner_markers:
            sub_units: list[StructuralUnit] = []
            first = inner_markers[0][0]
            if first > 0:
                sub_units.append(
                    StructuralUnit(
                        label=unit.label,
                        kind=unit.kind,
                        char_start=unit.char_start,
                        char_end=unit.char_start + first,
                        parent_path=unit.parent_path,
                        text=inner[:first],
                    )
                )
            local_stack: list[tuple[int, str]] = []
            for idx, (start, _end, token, kind) in enumerate(inner_markers):
                next_start = (
                    inner_markers[idx + 1][0]
                    if idx + 1 < len(inner_markers)
                    else len(inner)
                )
                hierarchy_key = _HIERARCHY_KIND_TO_KEY.get(kind)
                if hierarchy_key is not None:
                    local_stack = []
                    path = unit.parent_path + (f"{kind.value}:{token}",)
                    label = f"{kind.value}:{token}"
                else:
                    level = _marker_level(kind)
                    while local_stack and local_stack[-1][0] >= level:
                        local_stack.pop()
                    local_stack.append((level, f"{kind.value}:{token}"))
                    path = unit.parent_path + tuple(seg for _, seg in local_stack)
                    label = f"({token})"
                sub_units.append(
                    StructuralUnit(
                        label=label,
                        kind=kind.value,
                        char_start=unit.char_start + start,
                        char_end=unit.char_start + next_start,
                        parent_path=path,
                        text=inner[start:next_start],
                    )
                )
            if len(sub_units) > 1:
                pieces: list[_Piece] = []
                for sub in sub_units:
                    pieces.extend(
                        _subdivide_unit(
                            sub,
                            source_text=source_text,
                            tokens=tokens,
                            model_token_limit=model_token_limit,
                            depth=depth + 1,
                        )
                    )
                return _repair_coverage(
                    pieces,
                    text_len=unit.char_end - unit.char_start,
                    base_path=unit.parent_path,
                    abs_offset=unit.char_start,
                )

    sentence_spans = _sentence_spans(unit.text, unit.char_start)
    if len(sentence_spans) > 1:
        pieces = []
        for s_start, s_end in sentence_spans:
            sub = StructuralUnit(
                label=unit.label,
                kind=unit.kind,
                char_start=s_start,
                char_end=s_end,
                parent_path=unit.parent_path + ("sentence",),
                text=source_text[s_start:s_end],
            )
            sub_tok_count = len(
                [t for t in tokens if t.char_end > s_start and t.char_start < s_end]
            )
            if sub_tok_count <= model_token_limit:
                pieces.append(
                    _Piece(
                        char_start=s_start,
                        char_end=s_end,
                        parent_path=sub.parent_path,
                        split_mode=SplitMode.SENTENCE.value,
                    )
                )
            else:
                pieces.extend(
                    _hard_token_windows(
                        tokens,
                        char_start=s_start,
                        char_end=s_end,
                        model_token_limit=model_token_limit,
                        parent_path=sub.parent_path,
                    )
                )
        return pieces

    return _hard_token_windows(
        tokens,
        char_start=unit.char_start,
        char_end=unit.char_end,
        model_token_limit=model_token_limit,
        parent_path=unit.parent_path,
    )


# ---------------------------------------------------------------------------
# Public chunker
# ---------------------------------------------------------------------------


def validate_model_token_limit(model_token_limit: Any) -> int:
    """Require an explicit positive model token ceiling.

    Rejects ``None`` and values that would silently reuse the 4,096-row
    storage bound as a token limit without the caller opting in.
    """

    return _validate_model_token_limit(
        model_token_limit,
        error_type=ChunkerConfigError,
        physical_row_limit=PHYSICAL_ROW_LIMIT,
    )


def assert_exact_reconstruction(
    source_text: str, chunks: Sequence[LegalTextChunk | Mapping[str, Any]]
) -> str:
    """Fail closed when exclusive spans do not reconstruct *source_text*."""

    return _assert_exact_reconstruction(
        source_text,
        chunks,
        error_type=StateLawsChunkerError,
    )


def assert_chunks_within_limit(
    chunks: Sequence[LegalTextChunk | Mapping[str, Any]],
    model_token_limit: int,
) -> None:
    """Fail closed when any non-exempt chunk exceeds the model token limit."""

    _assert_chunks_within_limit(
        chunks,
        model_token_limit,
        validate_limit=validate_model_token_limit,
        count_tokens=count_tokens,
        chunk_type=LegalTextChunk,
        error_type=StateLawsChunkerError,
    )


def assert_legal_boundaries_preserved(
    source_text: str, chunks: Sequence[LegalTextChunk | Mapping[str, Any]]
) -> None:
    """Fail closed when a chunk splits a legal heading or parenthetical marker."""

    markers = find_structural_markers(source_text)
    records: list[tuple[int, int, str]] = []
    for chunk in chunks:
        if isinstance(chunk, LegalTextChunk):
            records.append((chunk.char_start, chunk.char_end, chunk.split_mode))
        else:
            records.append(
                (
                    int(chunk["char_start"]),
                    int(chunk["char_end"]),
                    str(chunk.get("split_mode") or ""),
                )
            )
    for start, end, _token, _kind in markers:
        for char_start, char_end, _mode in records:
            overlaps = char_start < end and char_end > start
            if not overlaps:
                continue
            contains = char_start <= start and char_end >= end
            if not contains:
                raise LegalBoundaryError(
                    f"chunk [{char_start}, {char_end}) splits legal marker "
                    f"[{start}, {end})"
                )


def resolve_legal_identity(
    *,
    jurisdiction: Any,
    section: Any,
    code_family: Any = None,
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
    kind: Any = "section",
    path: Any = None,
) -> LegalIdentity:
    """Build a durable identity, filling ``code_family`` from the catalog."""

    family = code_family
    if family is None or family == "":
        family = code_family_for(jurisdiction)
    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=family,
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
    )


class StateLawsChunker:
    """Structure-aware chunker for state statute bodies.

    Parameters
    ----------
    overlap_tokens:
        Number of trailing tokens from the previous exclusive span to prepend
        as embedding context. Does not affect exclusive reconstruction spans.
    max_chunks_per_section:
        Hard bound on emitted chunks for huge sections. Remaining text is
        force-packed; if still incomplete, ``truncated=True`` is set.
    tokenizer_id:
        Stable tokenizer identity recorded on every chunk.
    """

    def __init__(
        self,
        *,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
        tokenizer_id: str = DEFAULT_TOKENIZER_ID,
    ) -> None:
        if not isinstance(overlap_tokens, int) or overlap_tokens < 0:
            raise ChunkerConfigError("overlap_tokens must be a non-negative integer")
        if not isinstance(max_chunks_per_section, int) or max_chunks_per_section < 1:
            raise ChunkerConfigError("max_chunks_per_section must be >= 1")
        if not isinstance(tokenizer_id, str) or not tokenizer_id.strip():
            raise ChunkerConfigError("tokenizer_id must be a non-empty string")
        self.overlap_tokens = overlap_tokens
        self.max_chunks_per_section = max_chunks_per_section
        self.tokenizer_id = tokenizer_id.strip()

    def chunk_statute(
        self,
        text: str,
        *,
        model_token_limit: int,
        jurisdiction: Any,
        section: Any,
        code_family: Any = None,
        title: Any = None,
        chapter: Any = None,
        part: Any = None,
        article: Any = None,
        heading: str = "",
        subsection: Any = None,
        appendix: Any = None,
        note: Any = None,
        granule: Any = None,
        edition: Any = None,
        schedule: Any = None,
        kind: Any = "section",
        path: Any = None,
        overlap_tokens: Optional[int] = None,
        max_chunks_per_section: Optional[int] = None,
    ) -> ChunkingResult:
        """Chunk one statute body under an explicit model token ceiling."""

        limit = validate_model_token_limit(model_token_limit)
        overlap = self.overlap_tokens if overlap_tokens is None else overlap_tokens
        if not isinstance(overlap, int) or overlap < 0:
            raise ChunkerConfigError("overlap_tokens must be a non-negative integer")
        max_chunks = (
            self.max_chunks_per_section
            if max_chunks_per_section is None
            else max_chunks_per_section
        )
        if not isinstance(max_chunks, int) or max_chunks < 1:
            raise ChunkerConfigError("max_chunks_per_section must be >= 1")
        if overlap >= limit and limit > 0:
            overlap = max(0, limit - 1)

        if not isinstance(text, str):
            raise StateLawsChunkerError("text must be a string")
        source = normalize_chunk_text(text)

        identity = resolve_legal_identity(
            jurisdiction=jurisdiction,
            section=section,
            code_family=code_family,
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
        )
        parent_legal_id = identity.parent_legal_id
        legal_id = identity.legal_id
        cursor = identity_cursor(identity)

        tokens = tokenize(source)
        source_token_count = len(tokens)

        if source == "":
            return ChunkingResult(
                chunks=(),
                source_text=source,
                source_token_count=0,
                model_token_limit=limit,
                overlap_tokens=overlap,
                max_chunks_per_section=max_chunks,
                truncated=False,
                tokenizer_id=self.tokenizer_id,
                parent_legal_id=parent_legal_id,
                legal_id=legal_id,
                jurisdiction=identity.jurisdiction,
                code_family=identity.code_family,
            )

        if source_token_count <= limit:
            piece = _Piece(
                char_start=0,
                char_end=len(source),
                parent_path=_cursor_path(cursor, ("body",)),
                split_mode=SplitMode.WHOLE.value,
            )
            chunk = self._build_chunk(
                piece_group=[piece],
                chunk_index=0,
                source=source,
                tokens=tokens,
                parent_legal_id=parent_legal_id,
                legal_id=legal_id,
                identity=identity,
                heading=heading,
                model_token_limit=limit,
                overlap_tokens=0,
            )
            return ChunkingResult(
                chunks=(chunk,),
                source_text=source,
                source_token_count=source_token_count,
                model_token_limit=limit,
                overlap_tokens=overlap,
                max_chunks_per_section=max_chunks,
                truncated=False,
                tokenizer_id=self.tokenizer_id,
                parent_legal_id=parent_legal_id,
                legal_id=legal_id,
                jurisdiction=identity.jurisdiction,
                code_family=identity.code_family,
            )

        units = segment_structural_units(source, cursor=cursor)
        pieces: list[_Piece] = []
        for unit in units:
            pieces.extend(
                _subdivide_unit(
                    unit,
                    source_text=source,
                    tokens=tokens,
                    model_token_limit=limit,
                )
            )
        pieces = _repair_coverage(
            pieces, text_len=len(source), base_path=_cursor_path(cursor)
        )

        groups = _pack_pieces(pieces, tokens=tokens, model_token_limit=limit)

        truncated = False
        if len(groups) > max_chunks:
            kept = groups[: max(0, max_chunks - 1)]
            remainder_start = kept[-1][-1].char_end if kept else 0
            remainder_pieces = _hard_token_windows(
                tokens,
                char_start=remainder_start,
                char_end=len(source),
                model_token_limit=limit,
                parent_path=_cursor_path(cursor, ("hard-remainder",)),
            )
            rem_groups = _pack_pieces(
                remainder_pieces, tokens=tokens, model_token_limit=limit
            )
            remaining_slots = max_chunks - len(kept)
            if len(rem_groups) > remaining_slots:
                rem_groups = rem_groups[:remaining_slots]
                truncated = True
            groups = kept + rem_groups

        chunks: list[LegalTextChunk] = []
        for index, group in enumerate(groups):
            chunk = self._build_chunk(
                piece_group=group,
                chunk_index=index,
                source=source,
                tokens=tokens,
                parent_legal_id=parent_legal_id,
                legal_id=legal_id,
                identity=identity,
                heading=heading,
                model_token_limit=limit,
                overlap_tokens=overlap if index > 0 else 0,
            )
            chunks.append(chunk)
        if not truncated:
            assert_exact_reconstruction(source, chunks)
        assert_chunks_within_limit(chunks, limit)
        assert_legal_boundaries_preserved(source, chunks)

        return ChunkingResult(
            chunks=tuple(chunks),
            source_text=source,
            source_token_count=source_token_count,
            model_token_limit=limit,
            overlap_tokens=overlap,
            max_chunks_per_section=max_chunks,
            truncated=truncated,
            tokenizer_id=self.tokenizer_id,
            parent_legal_id=parent_legal_id,
            legal_id=legal_id,
            jurisdiction=identity.jurisdiction,
            code_family=identity.code_family,
        )

    def chunk_section(self, text: str, **kwargs: Any) -> ChunkingResult:
        """Alias for :meth:`chunk_statute` (section-oriented call sites)."""

        return self.chunk_statute(text, **kwargs)

    def chunk_corpus_row(
        self,
        row: Mapping[str, Any],
        *,
        model_token_limit: int,
        overlap_tokens: Optional[int] = None,
        max_chunks_per_section: Optional[int] = None,
    ) -> ChunkingResult:
        """Chunk one admitted corpus row using its durable identity."""

        if not isinstance(row, Mapping):
            raise StateLawsChunkerError("corpus row must be a mapping")
        identity = identity_from_row(row)
        hierarchy = parse_hierarchy_unit(row.get("hierarchy_unit"))
        text = str(row.get("text") or row.get("body") or "")
        heading = str(row.get("heading") or row.get("catchline") or "")
        return self.chunk_statute(
            text,
            model_token_limit=model_token_limit,
            jurisdiction=identity.jurisdiction,
            section=identity.section or hierarchy.get("section"),
            code_family=identity.code_family,
            title=identity.title or hierarchy.get("title"),
            chapter=identity.chapter or hierarchy.get("chapter"),
            part=identity.part or hierarchy.get("part"),
            article=identity.article or hierarchy.get("article"),
            heading=heading,
            subsection=identity.subsection,
            appendix=identity.appendix,
            note=identity.note,
            granule=identity.granule,
            edition=identity.edition,
            schedule=identity.schedule,
            kind=identity.kind,
            path=identity.path,
            overlap_tokens=overlap_tokens,
            max_chunks_per_section=max_chunks_per_section,
        )

    def _build_chunk(
        self,
        *,
        piece_group: Sequence[_Piece],
        chunk_index: int,
        source: str,
        tokens: Sequence[TokenSpan],
        parent_legal_id: str,
        legal_id: str,
        identity: LegalIdentity,
        heading: str,
        model_token_limit: int,
        overlap_tokens: int,
    ) -> LegalTextChunk:
        char_start = piece_group[0].char_start
        char_end = piece_group[-1].char_end
        exclusive_text = source[char_start:char_end]

        exclusive_toks = [
            t for t in tokens if t.char_end > char_start and t.char_start < char_end
        ]
        if exclusive_toks:
            token_start = exclusive_toks[0].index
            token_end = exclusive_toks[-1].index + 1
        else:
            token_start = token_index_covering_char(tokens, char_start)
            token_end = token_start

        context_token_start = token_start
        overlap_count = 0
        if overlap_tokens > 0 and token_start > 0:
            context_token_start = max(0, token_start - overlap_tokens)
            context_token_start = max(0, min(context_token_start, token_start))
            overlap_count = token_start - context_token_start

        if exclusive_toks or tokens:
            if context_token_start < len(tokens):
                context_char_start = (
                    tokens[context_token_start].char_start
                    if context_token_start < token_start
                    else char_start
                )
            else:
                context_char_start = char_start
        else:
            context_char_start = char_start

        context_char_start = min(context_char_start, char_start)
        embed_text = source[context_char_start:char_end]

        embed_tokens = count_tokens(embed_text)
        if embed_tokens > model_token_limit and overlap_count > 0:
            exclusive_count = len(exclusive_toks)
            allowed_overlap = max(0, model_token_limit - exclusive_count)
            context_token_start = max(0, token_start - allowed_overlap)
            overlap_count = token_start - context_token_start
            context_char_start = (
                tokens[context_token_start].char_start
                if overlap_count > 0 and context_token_start < len(tokens)
                else char_start
            )
            context_char_start = min(context_char_start, char_start)
            embed_text = source[context_char_start:char_end]
            embed_tokens = count_tokens(embed_text)

        limit_exempt = any(p.limit_exempt for p in piece_group)
        if embed_tokens > model_token_limit:
            limit_exempt = True

        split_modes = {p.split_mode for p in piece_group}
        if len(split_modes) == 1:
            split_mode = next(iter(split_modes))
        elif SplitMode.HARD.value in split_modes:
            split_mode = SplitMode.HARD.value
        elif SplitMode.SENTENCE.value in split_modes:
            split_mode = SplitMode.SENTENCE.value
        else:
            split_mode = SplitMode.STRUCTURE.value

        parent_path = max((p.parent_path for p in piece_group), key=len, default=())

        chunk_id = identity.chunk_id(chunk_index)
        seed = _cid_seed(
            parent_legal_id=parent_legal_id,
            chunk_index=chunk_index,
            exclusive_text=exclusive_text,
            char_start=char_start,
            char_end=char_end,
            token_start=token_start,
            token_end=token_end,
            parent_path=parent_path,
            split_mode=split_mode,
            tokenizer_id=self.tokenizer_id,
        )
        chunk_cid = chunk_cid_for_payload(seed)

        return LegalTextChunk(
            chunk_index=chunk_index,
            chunk_id=chunk_id,
            chunk_cid=chunk_cid,
            parent_legal_id=parent_legal_id,
            legal_id=legal_id,
            text=embed_text,
            exclusive_text=exclusive_text,
            char_start=char_start,
            char_end=char_end,
            token_start=token_start,
            token_end=token_end,
            token_count=embed_tokens,
            context_char_start=context_char_start,
            context_token_start=context_token_start,
            overlap_token_count=overlap_count,
            parent_path=parent_path,
            split_mode=split_mode,
            limit_exempt=limit_exempt,
            model_token_limit=model_token_limit,
            tokenizer_id=self.tokenizer_id,
            jurisdiction=identity.jurisdiction,
            code_family=identity.code_family,
            title=identity.title or "",
            chapter=identity.chapter or "",
            part=identity.part or "",
            article=identity.article or "",
            section=identity.section,
            heading=heading or "",
        )


def _repair_coverage(
    pieces: Sequence[_Piece],
    *,
    text_len: int,
    base_path: Sequence[str],
    abs_offset: int = 0,
) -> list[_Piece]:
    """Ensure pieces form a contiguous exclusive cover of a text region."""

    return repair_coverage(
        pieces,
        text_len=text_len,
        base_path=base_path,
        abs_offset=abs_offset,
        piece_factory=_Piece,
        hard_split_mode=SplitMode.HARD.value,
    )


def chunk_state_statute(
    text: str,
    *,
    model_token_limit: int,
    jurisdiction: Any,
    section: Any,
    **kwargs: Any,
) -> ChunkingResult:
    """Module-level convenience wrapper around :class:`StateLawsChunker`."""

    overlap = kwargs.pop("overlap_tokens", DEFAULT_OVERLAP_TOKENS)
    max_chunks = kwargs.pop("max_chunks_per_section", DEFAULT_MAX_CHUNKS_PER_SECTION)
    tokenizer_id = kwargs.pop("tokenizer_id", DEFAULT_TOKENIZER_ID)
    chunker = StateLawsChunker(
        overlap_tokens=overlap,
        max_chunks_per_section=max_chunks,
        tokenizer_id=tokenizer_id,
    )
    return chunker.chunk_statute(
        text,
        model_token_limit=model_token_limit,
        jurisdiction=jurisdiction,
        section=section,
        **kwargs,
    )


def chunk_corpus_row(
    row: Mapping[str, Any],
    *,
    model_token_limit: int,
    **kwargs: Any,
) -> ChunkingResult:
    """Chunk one canonical corpus row under an explicit model token ceiling."""

    overlap = kwargs.pop("overlap_tokens", DEFAULT_OVERLAP_TOKENS)
    max_chunks = kwargs.pop("max_chunks_per_section", DEFAULT_MAX_CHUNKS_PER_SECTION)
    tokenizer_id = kwargs.pop("tokenizer_id", DEFAULT_TOKENIZER_ID)
    chunker = StateLawsChunker(
        overlap_tokens=overlap,
        max_chunks_per_section=max_chunks,
        tokenizer_id=tokenizer_id,
    )
    return chunker.chunk_corpus_row(
        row,
        model_token_limit=model_token_limit,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Sealed boundary fixture (compact recipe)
# ---------------------------------------------------------------------------


def default_chunk_boundary_fixture_path() -> Path:
    """Return the default on-disk path for the sealed boundary fixture."""

    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "tests" / "fixtures" / "legal_ir" / "state_laws_chunk_boundaries.json"


def build_default_chunk_boundary_fixture_payload() -> dict[str, Any]:
    """Compact recipe of deterministic boundary cases (not a bulk golden dump)."""

    return {
        "description": (
            "Compact recipe for structure-aware state statute chunk boundary "
            "cases. Named cases supply source text and chunking parameters; "
            "per-jurisdiction cases expand from corpus fixture text. Expected "
            "boundaries are derived deterministically by the chunker rather "
            "than stored as bulk per-chunk envelopes."
        ),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "tokenizer_id": DEFAULT_TOKENIZER_ID,
        "physical_row_limit": PHYSICAL_ROW_LIMIT,
        "jurisdictions": list(CANONICAL_JURISDICTION_ORDER),
        "per_jurisdiction": {
            "chapter": "1",
            "expect": {
                "all_within_limit": True,
                "deterministic": True,
                "exact_reconstruction": True,
                "min_chunks": 1,
            },
            "min_chars": 80,
            "model_token_limit": 128,
            "overlap_tokens": 0,
            "section": "1.01",
            "title": "1",
        },
        "cases": [
            {
                "case_id": "short-whole-section",
                "jurisdiction": "OR",
                "code_family": "oregon-revised-statutes",
                "title": "16",
                "chapter": "163",
                "section": "163.005",
                "heading": "Definitions",
                "model_token_limit": 128,
                "overlap_tokens": 0,
                "text": (
                    "As used in this chapter, unless the context requires otherwise, "
                    "person means a human being and the provisions of this section "
                    "shall be construed together with the remainder of the chapter."
                ),
                "expect": {
                    "min_chunks": 1,
                    "max_chunks": 1,
                    "split_modes": ["whole"],
                    "exact_reconstruction": True,
                },
            },
            {
                "case_id": "subsection-structure",
                "jurisdiction": "CA",
                "code_family": "california-codes",
                "title": "1",
                "chapter": "1",
                "section": "26",
                "heading": "Persons capable of committing crimes",
                "model_token_limit": 48,
                "overlap_tokens": 8,
                "text": (
                    "All persons are capable of committing crimes except those belonging "
                    "to the following classes:\n"
                    "(a) Children under the age of 14, in the absence of clear proof "
                    "that at the time of committing the act charged against them they "
                    "knew its wrongfulness.\n"
                    "(b) Persons who are mentally incapacitated.\n"
                    "(c) Persons who committed the act charged under an ignorance or "
                    "mistake of fact, which disproves any criminal intent."
                ),
                "expect": {
                    "min_chunks": 2,
                    "exact_reconstruction": True,
                    "require_structure_split": True,
                    "parent_path_prefixes": [
                        [
                            "jurisdiction:CA",
                            "code:california-codes",
                            "title:1",
                            "chapter:1",
                            "section:26",
                        ]
                    ],
                },
            },
            {
                "case_id": "code-title-chapter-section-subsection",
                "jurisdiction": "TX",
                "code_family": "texas-statutes",
                "title": "2",
                "chapter": "6",
                "section": "6.01",
                "heading": "Requirement of voluntary act or omission",
                "model_token_limit": 40,
                "overlap_tokens": 4,
                "text": (
                    "PENAL CODE\n"
                    "TITLE 2. GENERAL PRINCIPLES OF CRIMINAL RESPONSIBILITY\n"
                    "CHAPTER 6. CULPABILITY GENERALLY\n"
                    "SECTION 6.01. Requirement of voluntary act or omission\n"
                    "(a) A person commits an offense only if the person voluntarily "
                    "engages in conduct, including an act, an omission, or possession.\n"
                    "(b) Possession is a voluntary act if the possessor knowingly obtains "
                    "or receives the thing possessed or is aware of the person's control "
                    "of the thing for a sufficient time to permit the person to terminate "
                    "control."
                ),
                "expect": {
                    "min_chunks": 2,
                    "exact_reconstruction": True,
                    "require_structure_split": True,
                    "require_hierarchy_path": True,
                },
            },
            {
                "case_id": "hard-split-no-markers",
                "jurisdiction": "FL",
                "code_family": "florida-statutes",
                "title": "46",
                "chapter": "775",
                "section": "775.01",
                "heading": "Common law of England",
                "model_token_limit": 16,
                "overlap_tokens": 4,
                "text": ("Word " * 80).strip() + ".",
                "expect": {
                    "min_chunks": 4,
                    "exact_reconstruction": True,
                    "require_hard_or_sentence": True,
                },
            },
            {
                "case_id": "huge-section-bounded",
                "jurisdiction": "NY",
                "code_family": "new-york-consolidated-laws",
                "title": "1",
                "chapter": "40",
                "section": "120.00",
                "heading": "Assault in the third degree",
                "model_token_limit": 20,
                "overlap_tokens": 2,
                "max_chunks_per_section": 8,
                "text_recipe": {
                    "kind": "repeat_sentence",
                    "sentence": (
                        "(a) A person is guilty of assault in the third degree when the "
                        "actor causes physical injury. "
                    ),
                    "repeat": 200,
                },
                "expect": {
                    "max_chunks": 8,
                    "bounded": True,
                    "all_within_limit": True,
                    "exact_reconstruction": False,
                },
            },
            {
                "case_id": "deterministic-boundaries",
                "jurisdiction": "DC",
                "code_family": "dc-official-code",
                "title": "22",
                "chapter": "4",
                "section": "22-404",
                "heading": "Assault or threatened assault in a menacing manner",
                "model_token_limit": 40,
                "overlap_tokens": 5,
                "text": (
                    "Whoever unlawfully assaults, or threatens another in a menacing "
                    "manner, shall be fined not more than the amount set forth in "
                    "section 22-3571.01 or imprisoned not more than 180 days, or both, "
                    "and in addition thereto, shall be required to execute a bond to "
                    "keep the peace for a period of not less than six months."
                ),
                "expect": {
                    "exact_reconstruction": True,
                    "deterministic": True,
                    "all_within_limit": True,
                },
            },
            {
                "case_id": "nested-paragraph-path",
                "jurisdiction": "IL",
                "code_family": "illinois-compiled-statutes",
                "title": "5",
                "chapter": "5",
                "section": "5-1",
                "heading": "Public information; agency rules",
                "model_token_limit": 48,
                "overlap_tokens": 4,
                "text": (
                    "Each agency shall make available to the public information as follows:\n"
                    "(a) Each agency shall separately state and currently publish for the "
                    "guidance of the public—\n"
                    "(1) descriptions of its central and field organization; and\n"
                    "(2) statements of the general course and method by which its functions "
                    "are channeled and determined.\n"
                    "(b) This section does not apply to matters that are—\n"
                    "(1) specifically authorized under criteria established by an Executive "
                    "order to be kept secret in the interest of national defense; or\n"
                    "(2) related solely to the internal personnel rules and practices of "
                    "an agency."
                ),
                "expect": {
                    "exact_reconstruction": True,
                    "min_chunks": 1,
                    "require_parent_paths": True,
                },
            },
        ],
    }


def expand_case_text(case: Mapping[str, Any]) -> str:
    """Materialize case text from inline ``text`` or a compact ``text_recipe``."""

    if "text" in case and case["text"] is not None:
        return str(case["text"])
    recipe = case.get("text_recipe")
    if not isinstance(recipe, Mapping):
        raise ChunkBoundaryFixtureError(
            f"case {case.get('case_id')!r} missing text/text_recipe"
        )
    kind = str(recipe.get("kind") or "")
    if kind == "repeat_sentence":
        sentence = str(recipe.get("sentence") or "")
        repeat = int(recipe.get("repeat") or 0)
        if not sentence or repeat < 1:
            raise ChunkBoundaryFixtureError(
                f"case {case.get('case_id')!r} has invalid repeat_sentence recipe"
            )
        return sentence * repeat
    if kind == "corpus_fixture_statute":
        jurisdiction = str(recipe.get("jurisdiction") or case.get("jurisdiction") or "")
        section = str(recipe.get("section") or case.get("section") or "")
        if not jurisdiction or not section:
            raise ChunkBoundaryFixtureError(
                f"case {case.get('case_id')!r} corpus_fixture_statute needs "
                "jurisdiction and section"
            )
        min_chars = int(recipe.get("min_chars") or 0)
        variant = str(recipe.get("variant") or "current")
        return fixture_statute_text(
            jurisdiction, section, min_chars=min_chars, variant=variant
        )
    raise ChunkBoundaryFixtureError(
        f"case {case.get('case_id')!r} has unknown text_recipe kind {kind!r}"
    )


def expand_per_jurisdiction_cases(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand the compact per-jurisdiction recipe into executable cases."""

    template = payload.get("per_jurisdiction") or {}
    if not isinstance(template, Mapping):
        raise ChunkBoundaryFixtureError("per_jurisdiction must be a mapping when present")
    jurisdictions = payload.get("jurisdictions") or []
    if not isinstance(jurisdictions, list) or not jurisdictions:
        raise ChunkBoundaryFixtureError("fixture must list jurisdictions")
    section = str(template.get("section") or "1.01")
    title = template.get("title", "1")
    chapter = template.get("chapter", "1")
    min_chars = int(template.get("min_chars") or 80)
    expect = dict(
        template.get("expect")
        or {"exact_reconstruction": True, "min_chunks": 1, "deterministic": True}
    )
    cases: list[dict[str, Any]] = []
    for raw_code in jurisdictions:
        code = str(raw_code).strip().upper()
        case: dict[str, Any] = {
            "case_id": f"per-jurisdiction-{code}",
            "jurisdiction": code,
            "section": section,
            "title": title,
            "chapter": chapter,
            "heading": f"{code} compact statute",
            "model_token_limit": int(template.get("model_token_limit") or 128),
            "overlap_tokens": int(template.get("overlap_tokens") or 0),
            "text_recipe": {
                "kind": "corpus_fixture_statute",
                "jurisdiction": code,
                "min_chars": min_chars,
                "section": section,
            },
            "expect": expect,
        }
        if template.get("code_family"):
            case["code_family"] = template["code_family"]
        cases.append(case)
    return cases


def load_chunk_boundary_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path is not None else default_chunk_boundary_fixture_path()
    if not fixture_path.is_file():
        raise ChunkBoundaryFixtureError(f"fixture not found: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChunkBoundaryFixtureError(f"invalid JSON in {fixture_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ChunkBoundaryFixtureError("fixture root must be an object")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise ChunkBoundaryFixtureError(
            f"unsupported fixture schema_version: {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise ChunkBoundaryFixtureError("fixture must contain a non-empty cases list")
    jurisdictions = payload.get("jurisdictions")
    if not isinstance(jurisdictions, list) or len(jurisdictions) != EXPECTED_JURISDICTION_COUNT:
        raise ChunkBoundaryFixtureError(
            "fixture jurisdictions must list the exact 51-jurisdiction set"
        )
    if tuple(str(code).upper() for code in jurisdictions) != CANONICAL_JURISDICTION_ORDER:
        raise ChunkBoundaryFixtureError(
            "fixture jurisdictions must equal CANONICAL_JURISDICTION_ORDER"
        )
    if payload.get("physical_row_limit") != PHYSICAL_ROW_LIMIT:
        raise ChunkBoundaryFixtureError(
            "fixture physical_row_limit must equal the 4096-row storage bound "
            "(never a token ceiling)"
        )
    return payload


def run_fixture_case(
    case: Mapping[str, Any],
    *,
    tokenizer_id: str = DEFAULT_TOKENIZER_ID,
) -> ChunkingResult:
    """Execute one sealed fixture case and return the chunking result."""

    text = expand_case_text(case)
    limit = validate_model_token_limit(case.get("model_token_limit"))
    overlap = int(case.get("overlap_tokens", DEFAULT_OVERLAP_TOKENS))
    max_chunks = int(case.get("max_chunks_per_section", DEFAULT_MAX_CHUNKS_PER_SECTION))
    chunker = StateLawsChunker(
        overlap_tokens=overlap,
        max_chunks_per_section=max_chunks,
        tokenizer_id=str(case.get("tokenizer_id") or tokenizer_id),
    )
    return chunker.chunk_statute(
        text,
        model_token_limit=limit,
        jurisdiction=case.get("jurisdiction"),
        section=case.get("section"),
        code_family=case.get("code_family"),
        title=case.get("title"),
        chapter=case.get("chapter"),
        part=case.get("part"),
        article=case.get("article"),
        heading=str(case.get("heading") or ""),
        subsection=case.get("subsection"),
        appendix=case.get("appendix"),
        note=case.get("note"),
        granule=case.get("granule"),
        edition=case.get("edition"),
        schedule=case.get("schedule"),
        kind=case.get("kind", "section"),
        path=case.get("path"),
    )


def boundary_fingerprint(result: ChunkingResult) -> list[dict[str, Any]]:
    """Compact deterministic boundary summary for a chunking result."""

    rows: list[dict[str, Any]] = []
    for chunk in result.chunks:
        rows.append(
            {
                "char_end": chunk.char_end,
                "char_start": chunk.char_start,
                "chunk_cid": chunk.chunk_cid,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "exclusive_sha256": content_sha256(chunk.exclusive_text),
                "limit_exempt": chunk.limit_exempt,
                "overlap_token_count": chunk.overlap_token_count,
                "parent_path": list(chunk.parent_path),
                "split_mode": chunk.split_mode,
                "token_count": chunk.token_count,
                "token_end": chunk.token_end,
                "token_start": chunk.token_start,
            }
        )
    return rows


def write_default_chunk_boundary_fixture(path: PathLike | None = None) -> Path:
    """Write the sealed compact boundary recipe to *path* (or default)."""

    fixture_path = Path(path) if path is not None else default_chunk_boundary_fixture_path()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_chunk_boundary_fixture_payload()
    for case in payload["cases"]:
        expand_case_text(case)
    for case in expand_per_jurisdiction_cases(payload):
        expand_case_text(case)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fixture_path.write_text(text, encoding="utf-8")
    return fixture_path


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "TASK_ID",
    "GOAL_ID",
    "PRODUCER",
    "PHYSICAL_ROW_LIMIT",
    "DEFAULT_OVERLAP_TOKENS",
    "DEFAULT_MAX_CHUNKS_PER_SECTION",
    "DEFAULT_TOKENIZER_ID",
    "StateLawsChunkerError",
    "ChunkerConfigError",
    "ChunkBoundaryFixtureError",
    "LegalBoundaryError",
    "SplitMode",
    "UnitKind",
    "TokenSpan",
    "StructuralUnit",
    "LegalTextChunk",
    "ChunkingResult",
    "StateLawsChunker",
    "normalize_chunk_text",
    "tokenize",
    "count_tokens",
    "find_hierarchy_headings",
    "find_parenthetical_markers",
    "find_structural_markers",
    "segment_structural_units",
    "validate_model_token_limit",
    "reconstruct_text",
    "assert_exact_reconstruction",
    "assert_chunks_within_limit",
    "assert_legal_boundaries_preserved",
    "resolve_legal_identity",
    "chunk_state_statute",
    "chunk_corpus_row",
    "chunk_cid_for_payload",
    "content_sha256",
    "canonical_json_bytes",
    "default_chunk_boundary_fixture_path",
    "build_default_chunk_boundary_fixture_payload",
    "expand_case_text",
    "expand_per_jurisdiction_cases",
    "load_chunk_boundary_fixture_payload",
    "run_fixture_case",
    "boundary_fingerprint",
    "write_default_chunk_boundary_fixture",
    "build_chunk_parent_id",
    "build_legal_id",
    "identity_from_row",
    "parse_chunk_id",
    "identity_cursor",
]
