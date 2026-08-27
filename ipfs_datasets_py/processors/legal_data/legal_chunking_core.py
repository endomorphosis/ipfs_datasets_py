"""Corpus-neutral mechanics shared by legal-text chunkers.

This module deliberately stops below legal hierarchy and identity policy.
It owns only deterministic text mechanics: normalization, whitespace-token
offsets, sentence and hard-window spans, greedy packing, coverage repair,
content addressing, and reconstruction/limit checks.  Dataset chunkers remain
responsible for interpreting legal markers, constructing parent paths and
identities, and defining their public row schemas.

Keeping that boundary narrow lets the U.S.-Code and state-law chunkers share
the algorithmic work without making either corpus's hierarchy a special case
inside the other.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_TOKEN_RE = re.compile(r"\S+")


class TokenLike(Protocol):
    """Minimal token-offset contract consumed by the shared mechanics."""

    char_start: int
    char_end: int


class PieceLike(Protocol):
    """Minimal exclusive-piece contract consumed by packing and repair."""

    char_start: int
    char_end: int
    parent_path: tuple[str, ...]
    split_mode: str
    limit_exempt: bool


ErrorType = type[Exception]


def normalize_chunk_text(text: str, *, error_type: ErrorType) -> str:
    """NFKC-normalize text while preserving the caller's error contract."""

    if not isinstance(text, str):
        raise error_type("text must be a string")
    if "\x00" in text:
        raise error_type("text must not contain NUL")
    return unicodedata.normalize("NFKC", text)


def whitespace_token_rows(
    text: str,
    *,
    error_type: ErrorType,
) -> list[tuple[int, int, int, str]]:
    """Return deterministic whitespace-token rows with character offsets."""

    if not isinstance(text, str):
        raise error_type("text must be a string")
    return [
        (index, match.start(), match.end(), match.group(0))
        for index, match in enumerate(_TOKEN_RE.finditer(text))
    ]


def token_index_covering_char(tokens: Sequence[TokenLike], char_pos: int) -> int:
    """Return the containing token index, or its insertion point."""

    if not tokens:
        return 0
    if char_pos <= tokens[0].char_start:
        return 0
    if char_pos >= tokens[-1].char_end:
        return len(tokens)
    lo, hi = 0, len(tokens) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        token = tokens[mid]
        if char_pos < token.char_start:
            hi = mid - 1
        elif char_pos >= token.char_end:
            lo = mid + 1
        else:
            return mid
    return lo


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Encode a mapping in the canonical form used for legal chunk CIDs."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(data: bytes | str) -> str:
    """Return the lowercase SHA-256 digest of bytes or UTF-8 text."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def chunk_cid_for_payload(payload: Mapping[str, Any]) -> str:
    """Return a deterministic CID, with a dependency-free SHA fallback."""

    raw = canonical_json_bytes(payload)
    digest = content_sha256(raw)
    try:
        from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

        return str(cid_for_bytes(raw))
    except Exception:  # noqa: BLE001 - stable fallback is part of the contract
        return f"sha256:{digest}"


def build_chunk_cid_seed(
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
    schema_version: str,
) -> dict[str, Any]:
    """Build the corpus-neutral portion of a chunk's content-address seed."""

    return {
        "char_end": char_end,
        "char_start": char_start,
        "chunk_index": chunk_index,
        "exclusive_text": exclusive_text,
        "parent_legal_id": parent_legal_id,
        "parent_path": list(parent_path),
        "schema_version": schema_version,
        "split_mode": split_mode,
        "token_end": token_end,
        "token_start": token_start,
        "tokenizer_id": tokenizer_id,
    }


def sentence_spans(text: str, abs_start: int) -> list[tuple[int, int]]:
    """Return contiguous absolute sentence spans within *text*."""

    if not text:
        return []
    boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(text))
    if not boundaries:
        if "\n" in text:
            spans: list[tuple[int, int]] = []
            cursor = 0
            for line in text.splitlines(keepends=True):
                spans.append((abs_start + cursor, abs_start + cursor + len(line)))
                cursor += len(line)
            return spans or [(abs_start, abs_start + len(text))]
        return [(abs_start, abs_start + len(text))]

    spans: list[tuple[int, int]] = []
    last = 0
    for match in boundaries:
        # Inter-sentence whitespace stays with the left span so coverage is
        # contiguous and exact reconstruction remains possible.
        end = match.end()
        if end > last:
            spans.append((abs_start + last, abs_start + end))
        last = match.end()
    if last < len(text):
        spans.append((abs_start + last, abs_start + len(text)))
    return spans


def token_count_in_span(
    tokens: Sequence[TokenLike],
    char_start: int,
    char_end: int,
) -> int:
    """Count tokens intersecting the half-open character span."""

    return sum(
        1
        for token in tokens
        if token.char_end > char_start and token.char_start < char_end
    )


def hard_token_windows[PieceT: PieceLike](
    tokens: Sequence[TokenLike],
    *,
    char_start: int,
    char_end: int,
    model_token_limit: int,
    parent_path: tuple[str, ...],
    piece_factory: Callable[..., PieceT],
    hard_split_mode: str,
    error_type: ErrorType,
) -> list[PieceT]:
    """Hard-split a character region into model-sized token windows."""

    if model_token_limit < 1:
        raise error_type("model_token_limit must be >= 1")

    selected = [
        token
        for token in tokens
        if token.char_end > char_start and token.char_start < char_end
    ]
    if not selected:
        return [
            piece_factory(
                char_start=char_start,
                char_end=char_end,
                parent_path=parent_path,
                split_mode=hard_split_mode,
            )
        ]

    pieces: list[PieceT] = []
    index = 0
    while index < len(selected):
        end_index = min(index + model_token_limit, len(selected))
        window_start = char_start if index == 0 else selected[index].char_start
        window_end = (
            char_end
            if end_index >= len(selected)
            else selected[end_index].char_start
        )
        pieces.append(
            piece_factory(
                char_start=window_start,
                char_end=window_end,
                parent_path=parent_path,
                split_mode=hard_split_mode,
                limit_exempt=False,
            )
        )
        index = end_index
    return pieces


def pack_pieces[PieceT: PieceLike](
    pieces: Sequence[PieceT],
    *,
    tokens: Sequence[TokenLike],
    model_token_limit: int,
) -> list[list[PieceT]]:
    """Greedily pack exclusive pieces under a token ceiling."""

    groups: list[list[PieceT]] = []
    current: list[PieceT] = []
    current_tokens = 0
    for piece in pieces:
        count = token_count_in_span(tokens, piece.char_start, piece.char_end)
        if count > model_token_limit:
            if current:
                groups.append(current)
                current = []
                current_tokens = 0
            groups.append([piece])
            continue
        if current and current_tokens + count > model_token_limit:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(piece)
        current_tokens += count
    if current:
        groups.append(current)
    return groups


def validate_model_token_limit(
    model_token_limit: Any,
    *,
    error_type: ErrorType,
    physical_row_limit: int,
) -> int:
    """Validate an explicit model ceiling without reusing the row bound."""

    if model_token_limit is None:
        raise error_type(
            "model_token_limit is required; pass the selected embedding "
            "model's maximum input tokens explicitly (do not reuse the "
            f"{physical_row_limit}-row storage bound as an implicit token limit)"
        )
    try:
        value = int(model_token_limit)
    except (TypeError, ValueError) as exc:
        raise error_type(
            f"model_token_limit must be a positive integer, got {model_token_limit!r}"
        ) from exc
    if value < 1:
        raise error_type(f"model_token_limit must be >= 1, got {value}")
    return value


def reconstruct_text(chunks: Sequence[Any]) -> str:
    """Reconstruct source text from sorted exclusive chunk spans."""

    records: list[tuple[int, int, str]] = []
    for chunk in chunks:
        if isinstance(chunk, Mapping):
            records.append(
                (
                    int(chunk["char_start"]),
                    int(chunk["char_end"]),
                    str(chunk["exclusive_text"]),
                )
            )
        else:
            records.append(
                (
                    int(chunk.char_start),
                    int(chunk.char_end),
                    str(chunk.exclusive_text),
                )
            )
    records.sort(key=lambda item: item[0])
    return "".join(text for _, _, text in records)


def assert_exact_reconstruction(
    source_text: str,
    chunks: Sequence[Any],
    *,
    error_type: ErrorType,
) -> str:
    """Return the reconstruction or raise the caller's corpus error type."""

    rebuilt = reconstruct_text(chunks)
    if rebuilt != source_text:
        raise error_type(
            "exact text reconstruction failed: "
            f"source_len={len(source_text)} rebuilt_len={len(rebuilt)}"
        )
    return rebuilt


def assert_chunks_within_limit(
    chunks: Sequence[Any],
    model_token_limit: int,
    *,
    validate_limit: Callable[[Any], int],
    count_tokens: Callable[[str], int],
    chunk_type: type[Any],
    error_type: ErrorType,
) -> None:
    """Enforce the exclusive and embeddable token ceilings."""

    limit = validate_limit(model_token_limit)
    for chunk in chunks:
        if isinstance(chunk, chunk_type):
            exempt = chunk.limit_exempt
            token_count = chunk.token_count
            embed_count = count_tokens(chunk.text)
            index = chunk.chunk_index
        else:
            exempt = bool(chunk.get("limit_exempt", False))
            token_count = int(chunk.get("token_count") or 0)
            embed_count = count_tokens(str(chunk.get("text") or ""))
            index = chunk.get("chunk_index")
        if exempt:
            continue
        if embed_count > limit or token_count > limit:
            raise error_type(
                f"non-exempt chunk {index} exceeds model_token_limit={limit}: "
                f"embed_tokens={embed_count} exclusive_tokens={token_count}"
            )


def repair_coverage[PieceT: PieceLike](
    pieces: Sequence[PieceT],
    *,
    text_len: int,
    base_path: Sequence[str],
    abs_offset: int,
    piece_factory: Callable[..., PieceT],
    hard_split_mode: str,
) -> list[PieceT]:
    """Repair pieces into a contiguous exclusive cover of a text region."""

    if text_len == 0:
        return []
    region_start = abs_offset
    region_end = abs_offset + text_len
    ordered = sorted(pieces, key=lambda piece: (piece.char_start, piece.char_end))
    repaired: list[PieceT] = []
    cursor = region_start
    for piece in ordered:
        if piece.char_end <= cursor:
            continue
        piece_start = max(piece.char_start, region_start)
        piece_end = min(piece.char_end, region_end)
        if piece_end <= cursor or piece_start >= region_end:
            continue
        if piece_start > cursor:
            repaired.append(
                piece_factory(
                    char_start=cursor,
                    char_end=piece_start,
                    parent_path=tuple(base_path) + ("gap",),
                    split_mode=hard_split_mode,
                )
            )
        start = max(piece_start, cursor)
        if start < piece_end:
            if start != piece.char_start or piece_end != piece.char_end:
                repaired.append(
                    piece_factory(
                        char_start=start,
                        char_end=piece_end,
                        parent_path=piece.parent_path,
                        split_mode=piece.split_mode,
                        limit_exempt=piece.limit_exempt,
                    )
                )
            else:
                repaired.append(piece)
            cursor = piece_end
        else:
            cursor = max(cursor, piece_end)
    if cursor < region_end:
        repaired.append(
            piece_factory(
                char_start=cursor,
                char_end=region_end,
                parent_path=tuple(base_path) + ("tail",),
                split_mode=hard_split_mode,
            )
        )
    return repaired


__all__ = [
    "assert_chunks_within_limit",
    "assert_exact_reconstruction",
    "build_chunk_cid_seed",
    "canonical_json_bytes",
    "chunk_cid_for_payload",
    "content_sha256",
    "hard_token_windows",
    "normalize_chunk_text",
    "pack_pieces",
    "reconstruct_text",
    "repair_coverage",
    "sentence_spans",
    "token_count_in_span",
    "token_index_covering_char",
    "validate_model_token_limit",
    "whitespace_token_rows",
]
