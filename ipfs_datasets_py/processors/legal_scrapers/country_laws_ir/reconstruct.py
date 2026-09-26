"""Reconstruct empty parent law bodies from article children.

Never invents legal text. Glue uses the same normalized strings as child
corpus fields. Eligible empty parents always get a law row (full glue,
streamed prefix, or title/number stub) — they are not dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import unicodedata
from typing import Any, Iterable

from .structure import normalize_legal_text

RECONSTRUCT_MAX_PARENT_CHARS = 2_000_000
RECONSTRUCT_STUB_MAX_CHARS = 8_192
RECONSTRUCT_PROCESS_BUDGET_BYTES = 512 * 1024 * 1024
RSS_ABORT_SKIP_FULL_CONCAT = frozenset({"france", "eu", "denmark"})
PARENT_TRUNCATED_MAX_CHARS = 40

_DIGIT_FOLD = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "〇": "0",
        "零": "0",
    }
)
_NUM_RUN = re.compile(r"\d+|\D+")


def fold_digits(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").translate(_DIGIT_FOLD)


def article_sort_key(article_number: str, source_id: str) -> tuple:
    folded = fold_digits(article_number or "")
    nums: list[int] = []
    rest: list[str] = []
    for run in _NUM_RUN.findall(folded) if folded else []:
        if run.isdigit():
            nums.append(int(run))
        else:
            rest.append(run)
    if not folded:
        return (0, (), "", source_id or "")
    if nums:
        return (1, tuple(nums), "".join(rest), source_id or "")
    return (2, (), folded, source_id or "")


def glue_piece(title: str, article_number: str, body: str) -> str:
    """One child's contribution to a reconstructed parent (normalized strings)."""
    title = title or ""
    article_number = article_number or ""
    body = body or ""
    chunk = title if title else article_number
    if chunk and not body.lstrip().startswith(chunk):
        return f"{chunk}\n{body}" if body else chunk
    return body


def glue_parent(pieces: Iterable[str]) -> str:
    return "\n\n".join(p for p in pieces if p)


@dataclass
class ReconstructResult:
    body: str
    reconstructed_from_articles: bool
    reconstruction_truncated: bool
    reconstruction_gap_note: str
    reconstruction_article_count: int
    reconstruction_article_ids: list[str] = field(default_factory=list)
    reconstruction_article_sha256: list[str] = field(default_factory=list)
    extra_bytes: int = 0
    is_stub: bool = False

    def extra_fields(self) -> dict[str, Any]:
        return {
            "reconstructed_from_articles": self.reconstructed_from_articles,
            "reconstruction_truncated": self.reconstruction_truncated,
            "reconstruction_gap_note": self.reconstruction_gap_note,
            "reconstruction_article_count": self.reconstruction_article_count,
            "reconstruction_article_ids": list(self.reconstruction_article_ids),
            "reconstruction_article_sha256": list(self.reconstruction_article_sha256),
        }


def parent_needs_reconstruct(parent_body: str, n_articles: int) -> bool:
    if n_articles < 1:
        return False
    body = parent_body or ""
    return (not body) or len(body) < PARENT_TRUNCATED_MAX_CHARS


def reconstruct_on() -> bool:
    return os.environ.get("COUNTRY_LAWS_RECONSTRUCT", "1").strip() not in {"0", "false", "off"}


def force_full_concat() -> bool:
    return os.environ.get("COUNTRY_LAWS_RECONSTRUCT_FULL", "").strip() in {"1", "true", "on"}


def process_budget_bytes() -> int:
    raw = os.environ.get("RECONSTRUCT_PROCESS_BUDGET_BYTES")
    if raw and raw.isdigit():
        return int(raw)
    return RECONSTRUCT_PROCESS_BUDGET_BYTES


def reconstruct_parent(
    *,
    slug: str,
    parent_body: str,
    parent_title: str,
    children: list[dict[str, str]],
    running_extra_bytes: int,
    sha256_hex,
) -> ReconstructResult:
    """Apply the five-way outcome table. ``children`` already normalized."""
    ordered = sorted(
        children,
        key=lambda c: article_sort_key(c.get("article_number") or "", c.get("id") or ""),
    )
    ids = [c.get("id") or "" for c in ordered]
    shas = [sha256_hex((c.get("body") or "").encode("utf-8")) for c in ordered]
    n = len(ordered)
    if n < 1 or not parent_needs_reconstruct(parent_body, n):
        return ReconstructResult(
            body=parent_body,
            reconstructed_from_articles=False,
            reconstruction_truncated=False,
            reconstruction_gap_note="",
            reconstruction_article_count=0,
        )

    stub_note = ""
    if slug in RSS_ABORT_SKIP_FULL_CONCAT and not force_full_concat():
        stub_note = "rss_abort_slug"
    elif running_extra_bytes >= process_budget_bytes():
        stub_note = "reconstruct_budget"

    if stub_note:
        parts: list[str] = []
        if parent_title:
            parts.append(parent_title)
        for child in ordered:
            label = child.get("title") or child.get("article_number") or ""
            if label:
                parts.append(label)
        stub = "\n".join(parts)[:RECONSTRUCT_STUB_MAX_CHARS]
        return ReconstructResult(
            body=stub,
            reconstructed_from_articles=True,
            reconstruction_truncated=False,
            reconstruction_gap_note=stub_note,
            reconstruction_article_count=n,
            reconstruction_article_ids=ids,
            reconstruction_article_sha256=shas,
            extra_bytes=0,
            is_stub=True,
        )

    acc: list[str] = []
    size = 0
    truncated = False
    for child in ordered:
        piece = glue_piece(
            child.get("title") or "",
            child.get("article_number") or "",
            child.get("body") or "",
        )
        if not piece:
            continue
        extra = (2 if acc else 0) + len(piece)
        if size + extra > RECONSTRUCT_MAX_PARENT_CHARS:
            room = RECONSTRUCT_MAX_PARENT_CHARS - size - (2 if acc else 0)
            if room > 0:
                acc.append(piece[:room])
                size = RECONSTRUCT_MAX_PARENT_CHARS
            truncated = True
            break
        acc.append(piece)
        size += extra
    body = glue_parent(acc)
    return ReconstructResult(
        body=body,
        reconstructed_from_articles=True,
        reconstruction_truncated=truncated,
        reconstruction_gap_note="",
        reconstruction_article_count=n,
        reconstruction_article_ids=ids,
        reconstruction_article_sha256=shas,
        extra_bytes=len(body.encode("utf-8")),
        is_stub=False,
    )


def expected_glue_from_children(children: list[dict[str, str]]) -> str:
    ordered = sorted(
        children,
        key=lambda c: article_sort_key(c.get("article_number") or "", c.get("id") or ""),
    )
    return glue_parent(
        glue_piece(c.get("title") or "", c.get("article_number") or "", c.get("body") or "")
        for c in ordered
    )
