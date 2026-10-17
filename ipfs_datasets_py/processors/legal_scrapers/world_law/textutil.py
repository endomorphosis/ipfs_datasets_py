"""Tag stripping shared by the municipal projectors. HTML is never copied into text."""

from __future__ import annotations

import hashlib
import html
import re

_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def null_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "N/A", "unknown"}:
        return None
    return text


def strip_markup(value: object) -> str | None:
    raw = null_text(value)
    if raw is None:
        return None
    cleaned = html.unescape(_TAG.sub("", raw)).strip()
    if not cleaned:
        return None
    lowered = cleaned.casefold()
    if "<html" in lowered or "<body" in lowered or "<" in cleaned:
        return None
    return cleaned


def calendar_date(value: object) -> str | None:
    text = null_text(value)
    if text is None or _DATE.fullmatch(text) is None:
        return None
    return text


def sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
