"""Official Massachusetts Constitution HTML walker.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ma``
(Apache-2.0). Walk h2/h3/h4/p plus unwrapped sibling text. Stop at
``ARTICLES OF AMENDMENT``. Part the First is flat articles; Part the Second
nests Chapter/Section/Article.

Local dump: ``MASSACHUSETTS_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

MA_CONST_URL = "https://malegislature.gov/Laws/Constitution"
_MA_CH_PREFIX_RE = re.compile(r"^Chapter\s+([IVXL]+)")
_MA_SEC_INLINE_RE = re.compile(r"Section\s+([IVXL]+)")
_MA_ARTICLE_H4_RE = re.compile(r"^Article\s+([IVXL]+)\.?$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered|annulled)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_massachusetts_chapter_heading(text: str) -> Tuple[str, str, Optional[str]]:
    match = _MA_CH_PREFIX_RE.match(text or "")
    if not match:
        return "", "", None
    rest = text[match.end() :]
    sec_match = _MA_SEC_INLINE_RE.search(rest)
    if sec_match:
        title = rest[: sec_match.start()]
        section = sec_match.group(1)
    else:
        title, section = rest, None
    return match.group(1), title.strip(" ,.;:"), section


def _walk_elements(node) -> Iterator[Tuple[str, str]]:
    from bs4 import NavigableString, Tag

    for child in getattr(node, "children", []):
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                yield ("text", text)
        elif isinstance(child, Tag):
            if child.name in ("h2", "h3", "h4", "p"):
                yield (child.name, child.get_text(" ", strip=True))
            elif child.name in ("script", "style"):
                continue
            else:
                yield from _walk_elements(child)


def parse_massachusetts_constitution_html(
    html: str,
    *,
    code_name: str = "Massachusetts Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.select_one(".content") or soup.find("main") or soup
    statutes: List[NormalizedStatute] = []
    part: Optional[int] = None
    cur_chapter: Optional[str] = None
    cur_section: Optional[str] = None
    cur_article: Optional[str] = None
    pending: List[str] = []
    chapter_pending: List[str] = []
    chapter_had_article = False

    def emit(art_id: str, number: str, body: str) -> None:
        raw = _WS.sub(" ", body).strip()
        if len(raw) < 40 or _RESERVED.search(raw[:160]):
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            return
        cite = f"Mass. Const. art. {art_id}, § {number}" if art_id != "1" else f"Mass. Const. Pt. 1, Art. {number}"
        if art_id != "1":
            cite = f"Mass. Const. Pt. 2, {art_id}, Art. {number}" if number != "0" else f"Mass. Const. Pt. 2, {art_id}"
        statutes.append(
            NormalizedStatute(
                state_code="MA",
                state_name="Massachusetts",
                statute_id=cite,
                code_name=code_name,
                title_number=art_id,
                section_number=number,
                section_name=(raw.split(".", 1)[0] or cite)[:200],
                full_text=raw[:14000],
                source_url=MA_CONST_URL,
                official_cite=cite,
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_massachusetts_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "malegislature_gov_constitution",
                    "article_id": art_id,
                    "skip_hydrate": True,
                },
            )
        )

    def flush_article() -> None:
        nonlocal pending, cur_article
        if cur_article is not None and part is not None:
            if part == 1:
                emit("1", cur_article, " ".join(pending))
            else:
                composite = f"2.{cur_chapter}.{cur_section}" if cur_section else f"2.{cur_chapter}"
                emit(composite, cur_article, " ".join(pending))
        pending = []
        cur_article = None

    def flush_chapter() -> None:
        nonlocal chapter_pending, chapter_had_article
        if part == 2 and cur_chapter and not chapter_had_article and chapter_pending:
            composite = f"2.{cur_chapter}.{cur_section}" if cur_section else f"2.{cur_chapter}"
            emit(composite, "0", " ".join(chapter_pending))
        chapter_pending = []
        chapter_had_article = False

    for kind, raw_text in _walk_elements(content):
        text = _WS.sub(" ", raw_text).strip()
        if not text:
            continue
        if kind == "h2":
            flush_article()
            flush_chapter()
            if text.upper() == "PART THE FIRST":
                part, cur_chapter, cur_section = 1, None, None
            elif text.upper() == "PART THE SECOND":
                part, cur_chapter, cur_section = 2, None, None
            elif text.upper().startswith("ARTICLES OF AMENDMENT"):
                break
            continue
        if kind == "h3":
            if part != 2 or not _MA_CH_PREFIX_RE.match(text):
                continue
            flush_article()
            flush_chapter()
            cur_chapter, _title, cur_section = parse_massachusetts_chapter_heading(text)
            continue
        if kind == "h4":
            match = _MA_ARTICLE_H4_RE.match(text)
            if not match or part is None:
                continue
            flush_article()
            cur_article = match.group(1)
            chapter_had_article = True
            continue
        if cur_article is not None:
            pending.append(text)
        if part == 2 and cur_chapter is not None:
            chapter_pending.append(text)
    flush_article()
    flush_chapter()
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MASSACHUSETTS_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
