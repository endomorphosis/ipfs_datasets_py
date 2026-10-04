"""Source selectors for the sentence policy used by the US Code inventory.

This deliberately keeps its simple punctuation policy (including its known
abbreviation limitations).  Unlike the legacy string-only helper, selectors
refer to the unmodified source and retain both Unicode and UTF-8 offsets.
"""
from __future__ import annotations

import re
from typing import Any

SENTENCE_POLICY = "uscode-whitespace-punctuation/v1"


def normalize_span_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source_selector(text: str, start_char: int, end_char: int) -> dict[str, Any]:
    """Return a half-open selector; bytes always refer to UTF-8 source bytes."""
    if (not isinstance(text, str) or type(start_char) is not int
            or type(end_char) is not int or not 0 <= start_char <= end_char <= len(text)):
        raise ValueError("source selector requires an exact in-range character interval")
    raw = text[start_char:end_char]
    return {"text": raw, "normalized_text": normalize_span_text(raw),
            "start_char": start_char, "end_char": end_char,
            "start_byte": len(text[:start_char].encode("utf-8")),
            "end_byte": len(text[:end_char].encode("utf-8"))}


def sentence_spans(text: str, *, start_char: int = 0,
                   end_char: int | None = None) -> list[dict[str, Any]]:
    """Split like ``constitution_inventory._sentences`` without losing offsets.

    Joining wrapped lines is whitespace normalization, not concatenating words.
    Whitespace between sentences is intentionally outside the returned spans;
    callers needing a complete inventory must record those omission intervals.
    No sentence is truncated or divided to satisfy a model's input limit.
    """
    end_char = len(text) if end_char is None else end_char
    source_selector(text, start_char, end_char)
    body = text[start_char:end_char]
    boundaries = [0]
    segments = []
    for match in re.finditer(r"(?<=[.!?])\s+", body):
        segments.append((boundaries[-1], match.start()))
        boundaries.append(match.end())
    segments.append((boundaries[-1], len(body)))
    result = []
    for left, right in segments:
        fragment = body[left:right]
        left += len(fragment) - len(fragment.lstrip())
        right -= len(fragment) - len(fragment.rstrip())
        if left < right:
            result.append(source_selector(text, start_char + left, start_char + right))
    return result
