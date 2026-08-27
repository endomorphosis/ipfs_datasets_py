"""Structure-aware U.S. Code legal text chunking (USCIR-007).

This module owns semantic segmentation of statutory text for the
``publicus-ir-graphrag/v2`` US Code release. It deliberately does **not**
perform physical Parquet sharding (that is USCIR-009) and never treats the
4,096-row storage bound as a model token ceiling.

Design invariants
-----------------
* ``model_token_limit`` is an **explicit required argument**. Callers must
  pass the selected embedding model's maximum input tokens; there is no
  silent default of 4,096.
* Oversized provisions are split on subsection / paragraph / clause markers
  first, then sentences, then hard token windows.
* Every chunk records stable character and token offsets, a parent path, a
  deterministic chunk identity (via :mod:`uscode_identity`), and a
  content-addressed chunk CID.
* Exclusive ``(char_start, char_end)`` spans of a section's chunks cover the
  full source text without gaps or overlaps, enabling exact reconstruction.
  Controlled overlap is carried only in the embeddable ``text`` field.
* Non-exempt chunks never exceed the selected model token limit. The only
  exempt case is a single unsplittable token longer than the limit.
* Huge-section output is bounded by ``max_chunks_per_section``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data import legal_chunking_core as _chunking_core
from ipfs_datasets_py.processors.legal_data.uscode_identity import (
    LegalIdentity,
    build_chunk_parent_id,
    build_legal_id,
)

SCHEMA_VERSION = "uscode-chunker-v1"
FIXTURE_SCHEMA_VERSION = "uscode-chunk-boundaries-v1"

# Physical retrieval-unit bound (rows/pointers). Documented only — never used
# as an implicit model token ceiling.
PHYSICAL_ROW_LIMIT = 4096

DEFAULT_OVERLAP_TOKENS = 32
DEFAULT_MAX_CHUNKS_PER_SECTION = 512
DEFAULT_TOKENIZER_ID = "uscode-whitespace-v1"
DEFAULT_JURISDICTION = "US"

# Parenthetical statutory markers: (a), (1), (A), (i), (iv), (I), ...
_SUBSEC_MARKER_RE = re.compile(r"\(([0-9A-Za-z]{1,6})\)")
_ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)

_COMMON_ROMAN_LOWER = frozenset(
    {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}
)
_COMMON_ROMAN_UPPER = frozenset(s.upper() for s in _COMMON_ROMAN_LOWER)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# Preserve the existing module-level API while binding all corpus-neutral
# mechanics to one implementation shared with the state-law chunker.
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


class UscodeChunkerError(ValueError):
    """Base error for structure-aware chunking failures."""


class ChunkerConfigError(UscodeChunkerError):
    """Raised when chunking configuration is invalid."""


class ChunkBoundaryFixtureError(UscodeChunkerError):
    """Raised when the sealed chunk-boundary fixture is malformed."""


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
    """Structural unit kind at a marker."""

    PREAMBLE = "preamble"
    SUBSECTION = "subsection"  # (a), (b), ...
    PARAGRAPH = "paragraph"  # (1), (2), ...
    SUBPARAGRAPH = "subparagraph"  # (A), (B), ...
    CLAUSE = "clause"  # (i), (ii), ...
    SUBCLAUSE = "subclause"  # (I), (II), ...
    OTHER = "other"


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
    """NFKC-normalize statutory text without changing length semantics.

    NFKC may change length for compatibility characters; callers that need
    exact reconstruction must chunk the **same** normalized string they
    reconstruct against. The chunker always normalizes once at entry.
    """

    return _normalize_chunk_text(text, error_type=UscodeChunkerError)


def tokenize(text: str) -> list[TokenSpan]:
    """Tokenize *text* with the sealed whitespace tokenizer.

    Tokens are maximal non-whitespace runs. Offsets are half-open
    ``[char_start, char_end)`` into *text*. Empty / whitespace-only text
    yields an empty list.
    """

    return [
        TokenSpan(index=index, char_start=start, char_end=end, text=token_text)
        for index, start, end, token_text in whitespace_token_rows(
            text,
            error_type=UscodeChunkerError,
        )
    ]


def count_tokens(text: str) -> int:
    """Return the deterministic token count for *text*."""

    return len(tokenize(text))


# ---------------------------------------------------------------------------
# Structural marker detection
# ---------------------------------------------------------------------------


def _classify_marker_kind(token: str, prev_kind: Optional[str]) -> UnitKind:
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
        UnitKind.SUBSECTION: 1,
        UnitKind.PARAGRAPH: 2,
        UnitKind.SUBPARAGRAPH: 3,
        UnitKind.CLAUSE: 4,
        UnitKind.SUBCLAUSE: 5,
        UnitKind.OTHER: 6,
    }
    return order.get(kind, 6)


def find_structural_markers(text: str) -> list[tuple[int, int, str, UnitKind]]:
    """Return ``(start, end, token, kind)`` for statutory parenthetical markers.

    Markers are accepted only at legal left/right boundaries so citations
    like ``section 552(a)(1)`` mid-sentence are still recognized when
    parentheticals are well-formed, while long alphanumeric noise is rejected.
    """

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
        # Allow tight chains such as ``(a)(1)`` (right paren before next marker).
        valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.()[]"
        valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
        if not (valid_left and valid_right):
            continue

        kind = _classify_marker_kind(token, prev_kind)
        prev_kind = kind.value
        markers.append((start, end, token, kind))
    return markers


@dataclass(frozen=True, slots=True)
class StructuralUnit:
    """One exclusive structural span of a section body."""

    label: str
    kind: str
    char_start: int
    char_end: int
    parent_path: tuple[str, ...]
    text: str

    @property
    def token_count(self) -> int:
        return count_tokens(self.text)


def segment_structural_units(text: str, *, base_path: Sequence[str] = ()) -> list[StructuralUnit]:
    """Split *text* into exclusive structural units covering the full string.

    Units include an optional preamble (text before the first marker) and one
    unit per top-level marker span through the next same-or-higher-level
    marker. Nested markers are retained inside the parent unit's text so
    deeper packing can re-segment if the parent is oversized.
    """

    if not text:
        return []

    markers = find_structural_markers(text)
    base = tuple(base_path)

    if not markers:
        return [
            StructuralUnit(
                label="body",
                kind=UnitKind.PREAMBLE.value,
                char_start=0,
                char_end=len(text),
                parent_path=base + ("body",),
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
                parent_path=base + ("preamble",),
                text=preamble,
            )
        )

    # Emit one unit per marker from marker start to next marker start (or end).
    # Parent path tracks nesting via level stack over marker labels.
    stack: list[tuple[int, str]] = []  # (level, path_segment)
    for idx, (start, _end, token, kind) in enumerate(markers):
        level = _marker_level(kind)
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        label = f"({token})"
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, f"{kind.value}:{token}"))
        path = base + tuple(seg for _, seg in stack)
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
    """One semantic chunk of a U.S. Code provision."""

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
    title: str = ""
    section: str = ""
    heading: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_path"] = list(self.parent_path)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalTextChunk":
        if not isinstance(value, Mapping):
            raise UscodeChunkerError("chunk payload must be a mapping")
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
            title=str(value.get("title") or ""),
            section=str(value.get("section") or ""),
            heading=str(value.get("heading") or ""),
        )


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """Result of chunking one section body."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks": [c.to_dict() for c in self.chunks],
            "source_text": self.source_text,
            "source_token_count": self.source_token_count,
            "model_token_limit": self.model_token_limit,
            "overlap_tokens": self.overlap_tokens,
            "max_chunks_per_section": self.max_chunks_per_section,
            "truncated": self.truncated,
            "tokenizer_id": self.tokenizer_id,
            "schema_version": self.schema_version,
            "parent_legal_id": self.parent_legal_id,
            "legal_id": self.legal_id,
            "chunk_count": len(self.chunks),
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
        return [
            _Piece(
                char_start=unit.char_start,
                char_end=unit.char_end,
                parent_path=unit.parent_path,
                split_mode=SplitMode.STRUCTURE.value
                if unit.kind != UnitKind.PREAMBLE.value
                else SplitMode.WHOLE.value,
            )
        ]

    # Depth-bounded re-segmentation of nested markers inside this unit.
    if depth < 4:
        inner = unit.text
        # Re-find markers strictly inside unit (skip the unit's own leading marker).
        inner_markers = find_structural_markers(inner)
        # Drop a marker that sits at offset 0 (the unit's own label).
        inner_markers = [m for m in inner_markers if m[0] > 0]
        if inner_markers:
            # Build sub-units relative to unit. Nesting is tracked only among
            # markers *inside* this unit; the unit parent_path is a fixed prefix.
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
                level = _marker_level(kind)
                next_start = (
                    inner_markers[idx + 1][0]
                    if idx + 1 < len(inner_markers)
                    else len(inner)
                )
                while local_stack and local_stack[-1][0] >= level:
                    local_stack.pop()
                local_stack.append((level, f"{kind.value}:{token}"))
                path = unit.parent_path + tuple(seg for _, seg in local_stack)
                sub_units.append(
                    StructuralUnit(
                        label=f"({token})",
                        kind=kind.value,
                        char_start=unit.char_start + start,
                        char_end=unit.char_start + next_start,
                        parent_path=path,
                        text=inner[start:next_start],
                    )
                )
            # Only accept if we actually split into smaller pieces.
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

    # Sentence-level split.
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

    # Hard token windows as last resort.
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
        error_type=UscodeChunkerError,
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
        error_type=UscodeChunkerError,
    )


class UscodeChunker:
    """Structure-aware chunker for U.S. Code section bodies.

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

    def chunk_section(
        self,
        text: str,
        *,
        model_token_limit: int,
        title: Any,
        section: Any,
        heading: str = "",
        jurisdiction: Any = DEFAULT_JURISDICTION,
        appendix: Any = None,
        note: Any = None,
        granule: Any = None,
        edition: Any = None,
        schedule: Any = None,
        kind: Any = "section",
        chapter: Any = None,
        overlap_tokens: Optional[int] = None,
        max_chunks_per_section: Optional[int] = None,
    ) -> ChunkingResult:
        """Chunk one section body under an explicit model token ceiling."""

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
        # Overlap must leave room for at least one new token when limit > 1.
        if overlap >= limit and limit > 0:
            # Allow overlap == 0 always; if overlap >= limit, clamp to limit-1
            # only when limit > 1, else force 0.
            overlap = max(0, limit - 1)

        if not isinstance(text, str):
            raise UscodeChunkerError("text must be a string")
        source = normalize_chunk_text(text)

        identity = LegalIdentity(
            title=title,
            section=section,
            jurisdiction=jurisdiction,
            appendix=appendix,
            note=note,
            granule=granule,
            edition=edition,
            schedule=schedule,
            kind=kind,
            chapter=chapter,
        )
        parent_legal_id = identity.parent_legal_id
        legal_id = identity.legal_id
        base_path = (
            f"title:{identity.title}",
            f"section:{identity.section}",
        )

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
            )

        # Fast path: whole section fits.
        if source_token_count <= limit:
            piece = _Piece(
                char_start=0,
                char_end=len(source),
                parent_path=base_path + ("body",),
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
            )

        units = segment_structural_units(source, base_path=base_path)
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
        # Ensure full coverage even if segmentation missed a gap.
        pieces = _repair_coverage(pieces, text_len=len(source), base_path=base_path)

        groups = _pack_pieces(pieces, tokens=tokens, model_token_limit=limit)

        truncated = False
        if len(groups) > max_chunks:
            # Bound huge-section behavior: keep the first max_chunks-1 groups,
            # then hard-window the remainder into the final slot budget.
            kept = groups[: max(0, max_chunks - 1)]
            remainder_start = kept[-1][-1].char_end if kept else 0
            remainder_pieces = _hard_token_windows(
                tokens,
                char_start=remainder_start,
                char_end=len(source),
                model_token_limit=limit,
                parent_path=base_path + ("hard-remainder",),
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

        # Exclusive token range: tokens overlapping [char_start, char_end).
        exclusive_toks = [
            t for t in tokens if t.char_end > char_start and t.char_start < char_end
        ]
        if exclusive_toks:
            token_start = exclusive_toks[0].index
            token_end = exclusive_toks[-1].index + 1
        else:
            token_start = token_index_covering_char(tokens, char_start)
            token_end = token_start

        # Overlap context: take up to overlap_tokens before exclusive start.
        context_token_start = token_start
        overlap_count = 0
        if overlap_tokens > 0 and token_start > 0:
            context_token_start = max(0, token_start - overlap_tokens)
            # Do not reach into tokens already beyond previous exclusive end
            # in a way that reorders — overlap is simply previous tokens.
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

        # Ensure context never starts after exclusive start.
        context_char_start = min(context_char_start, char_start)
        embed_text = source[context_char_start:char_end]

        # If embed text still exceeds limit due to overlap, shrink overlap.
        embed_tokens = count_tokens(embed_text)
        if embed_tokens > model_token_limit and overlap_count > 0:
            # Reduce overlap until embed fits (exclusive must already fit).
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
            # Pathological: exclusive content itself exceeds limit (should only
            # happen for unsplittable edge cases). Mark exempt.
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

        # Prefer deepest parent path among pieces.
        parent_path = max((p.parent_path for p in piece_group), key=len, default=())

        chunk_id = f"{parent_legal_id}#chunk={chunk_index:04d}"
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
            title=identity.title,
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
    """Ensure pieces form a contiguous exclusive cover of a text region.

    When ``abs_offset`` is 0 and ``text_len`` is the full source length, pieces
    cover ``[0, text_len)``. When repairing a sub-unit, pass the unit's
    ``char_start`` as ``abs_offset`` and the unit length as ``text_len`` so
    coverage is checked over ``[abs_offset, abs_offset + text_len)``.
    """

    return repair_coverage(
        pieces,
        text_len=text_len,
        base_path=base_path,
        abs_offset=abs_offset,
        piece_factory=_Piece,
        hard_split_mode=SplitMode.HARD.value,
    )


def chunk_uscode_section(
    text: str,
    *,
    model_token_limit: int,
    title: Any,
    section: Any,
    **kwargs: Any,
) -> ChunkingResult:
    """Module-level convenience wrapper around :class:`UscodeChunker`."""

    overlap = kwargs.pop("overlap_tokens", DEFAULT_OVERLAP_TOKENS)
    max_chunks = kwargs.pop("max_chunks_per_section", DEFAULT_MAX_CHUNKS_PER_SECTION)
    tokenizer_id = kwargs.pop("tokenizer_id", DEFAULT_TOKENIZER_ID)
    chunker = UscodeChunker(
        overlap_tokens=overlap,
        max_chunks_per_section=max_chunks,
        tokenizer_id=tokenizer_id,
    )
    return chunker.chunk_section(
        text,
        model_token_limit=model_token_limit,
        title=title,
        section=section,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Sealed boundary fixture (compact recipe)
# ---------------------------------------------------------------------------


def default_chunk_boundary_fixture_path() -> Path:
    """Return the default on-disk path for the sealed boundary fixture."""

    # ipfs_datasets_py/processors/legal_data/this_file.py → repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "tests" / "fixtures" / "legal_ir" / "uscode_chunk_boundaries.json"


def build_default_chunk_boundary_fixture_payload() -> dict[str, Any]:
    """Compact recipe of deterministic boundary cases (not a bulk golden dump)."""

    return {
        "description": (
            "Compact recipe for structure-aware US Code chunk boundary cases. "
            "Each case supplies source text and chunking parameters; expected "
            "boundaries are derived deterministically by the chunker rather "
            "than stored as bulk per-chunk envelopes."
        ),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "tokenizer_id": DEFAULT_TOKENIZER_ID,
        "physical_row_limit": PHYSICAL_ROW_LIMIT,
        "cases": [
            {
                "case_id": "short-whole-section",
                "title": "35",
                "section": "101",
                "heading": "Inventions patentable",
                "model_token_limit": 128,
                "overlap_tokens": 0,
                "text": (
                    "Whoever invents or discovers any new and useful process, "
                    "machine, manufacture, or composition of matter, or any new "
                    "and useful improvement thereof, may obtain a patent therefor, "
                    "subject to the conditions and requirements of this title."
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
                "title": "5",
                "section": "552",
                "heading": "Public information; agency rules, opinions, orders, records, and proceedings",
                "model_token_limit": 64,
                "overlap_tokens": 8,
                "text": (
                    "Each agency shall make available to the public information as follows:\n"
                    "(a) Each agency shall separately state and currently publish in the "
                    "Federal Register for the guidance of the public—\n"
                    "(1) descriptions of its central and field organization; and\n"
                    "(2) statements of the general course and method by which its functions "
                    "are channeled and determined.\n"
                    "(b) This section does not apply to matters that are—\n"
                    "(1) specifically authorized under criteria established by an Executive "
                    "order to be kept secret in the interest of national defense; or\n"
                    "(2) related solely to the internal personnel rules and practices of an agency."
                ),
                "expect": {
                    "min_chunks": 2,
                    "exact_reconstruction": True,
                    "require_structure_split": True,
                    "parent_path_prefixes": [
                        ["title:5", "section:552"],
                    ],
                },
            },
            {
                "case_id": "hard-split-no-markers",
                "title": "18",
                "section": "1001",
                "heading": "Statements or entries generally",
                "model_token_limit": 16,
                "overlap_tokens": 4,
                "text": (
                    "Word " * 80
                ).strip()
                + ".",
                "expect": {
                    "min_chunks": 4,
                    "exact_reconstruction": True,
                    "require_hard_or_sentence": True,
                },
            },
            {
                "case_id": "huge-section-bounded",
                "title": "26",
                "section": "501",
                "heading": "Exemption from tax on corporations",
                "model_token_limit": 20,
                "overlap_tokens": 2,
                "max_chunks_per_section": 8,
                "text_recipe": {
                    "kind": "repeat_sentence",
                    "sentence": (
                        "(a) An organization described in subsection (c) or (d) shall be exempt. "
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
                "title": "42",
                "section": "1983",
                "heading": "Civil action for deprivation of rights",
                "model_token_limit": 40,
                "overlap_tokens": 5,
                "text": (
                    "Every person who, under color of any statute, ordinance, regulation, "
                    "custom, or usage, of any State or Territory or the District of Columbia, "
                    "subjects, or causes to be subjected, any citizen of the United States or "
                    "other person within the jurisdiction thereof to the deprivation of any "
                    "rights, privileges, or immunities secured by the Constitution and laws, "
                    "shall be liable to the party injured in an action at law, suit in equity, "
                    "or other proper proceeding for redress, except that in any action brought "
                    "against a judicial officer for an act or omission taken in such officer's "
                    "judicial capacity, injunctive relief shall not be granted unless a "
                    "declaratory decree was violated or declaratory relief was unavailable."
                ),
                "expect": {
                    "exact_reconstruction": True,
                    "deterministic": True,
                    "all_within_limit": True,
                },
            },
            {
                "case_id": "nested-paragraph-path",
                "title": "17",
                "section": "107",
                "heading": "Limitations on exclusive rights: Fair use",
                "model_token_limit": 48,
                "overlap_tokens": 4,
                "text": (
                    "Notwithstanding the provisions of sections 106 and 106A, the fair use "
                    "of a copyrighted work is not an infringement of copyright.\n"
                    "(a) In determining whether the use made of a work in any particular case "
                    "is a fair use the factors to be considered shall include—\n"
                    "(1) the purpose and character of the use, including whether such use is "
                    "of a commercial nature or is for nonprofit educational purposes;\n"
                    "(2) the nature of the copyrighted work;\n"
                    "(3) the amount and substantiality of the portion used; and\n"
                    "(4) the effect of the use upon the potential market for or value of the "
                    "copyrighted work.\n"
                    "(b) The fact that a work is unpublished shall not itself bar a finding "
                    "of fair use if such finding is made upon consideration of all the above factors."
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
    raise ChunkBoundaryFixtureError(
        f"case {case.get('case_id')!r} has unknown text_recipe kind {kind!r}"
    )


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
    chunker = UscodeChunker(
        overlap_tokens=overlap,
        max_chunks_per_section=max_chunks,
        tokenizer_id=str(case.get("tokenizer_id") or tokenizer_id),
    )
    return chunker.chunk_section(
        text,
        model_token_limit=limit,
        title=case.get("title"),
        section=case.get("section"),
        heading=str(case.get("heading") or ""),
        jurisdiction=case.get("jurisdiction", DEFAULT_JURISDICTION),
        appendix=case.get("appendix"),
        note=case.get("note"),
        granule=case.get("granule"),
        edition=case.get("edition"),
        schedule=case.get("schedule"),
        kind=case.get("kind", "section"),
        chapter=case.get("chapter"),
    )


def boundary_fingerprint(result: ChunkingResult) -> list[dict[str, Any]]:
    """Compact deterministic boundary summary for a chunking result."""

    rows: list[dict[str, Any]] = []
    for chunk in result.chunks:
        rows.append(
            {
                "chunk_index": chunk.chunk_index,
                "chunk_id": chunk.chunk_id,
                "chunk_cid": chunk.chunk_cid,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "token_start": chunk.token_start,
                "token_end": chunk.token_end,
                "token_count": chunk.token_count,
                "overlap_token_count": chunk.overlap_token_count,
                "parent_path": list(chunk.parent_path),
                "split_mode": chunk.split_mode,
                "limit_exempt": chunk.limit_exempt,
                "exclusive_sha256": content_sha256(chunk.exclusive_text),
            }
        )
    return rows


def write_default_chunk_boundary_fixture(path: PathLike | None = None) -> Path:
    """Write the sealed compact boundary recipe to *path* (or default)."""

    fixture_path = Path(path) if path is not None else default_chunk_boundary_fixture_path()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_chunk_boundary_fixture_payload()
    # Smoke-expand every case before writing.
    for case in payload["cases"]:
        expand_case_text(case)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fixture_path.write_text(text, encoding="utf-8")
    return fixture_path


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "PHYSICAL_ROW_LIMIT",
    "DEFAULT_OVERLAP_TOKENS",
    "DEFAULT_MAX_CHUNKS_PER_SECTION",
    "DEFAULT_TOKENIZER_ID",
    "DEFAULT_JURISDICTION",
    "UscodeChunkerError",
    "ChunkerConfigError",
    "ChunkBoundaryFixtureError",
    "SplitMode",
    "UnitKind",
    "TokenSpan",
    "StructuralUnit",
    "LegalTextChunk",
    "ChunkingResult",
    "UscodeChunker",
    "normalize_chunk_text",
    "tokenize",
    "count_tokens",
    "find_structural_markers",
    "segment_structural_units",
    "validate_model_token_limit",
    "reconstruct_text",
    "assert_exact_reconstruction",
    "assert_chunks_within_limit",
    "chunk_uscode_section",
    "chunk_cid_for_payload",
    "content_sha256",
    "canonical_json_bytes",
    "default_chunk_boundary_fixture_path",
    "build_default_chunk_boundary_fixture_payload",
    "expand_case_text",
    "load_chunk_boundary_fixture_payload",
    "run_fixture_case",
    "boundary_fingerprint",
    "write_default_chunk_boundary_fixture",
    "build_chunk_parent_id",
    "build_legal_id",
]
