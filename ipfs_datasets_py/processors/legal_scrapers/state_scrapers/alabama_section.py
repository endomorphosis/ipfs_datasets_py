"""Official Alabama ALISON GraphQL section parser.

Adapted from Vaquill-AI/open-us-law ``scrapeAL.py`` (Apache-2.0).
The official Code of Alabama 1975 is a GraphQL SPA. Section bodies are
HTML ``<p>`` blocks; ``history`` is dropped. Reserved labels are skipped.

Local dumps: ``ALABAMA_SECTION_JSON`` (one section object) and
``ALABAMA_TITLES_TEXT`` (flat Title/Chapter/Section tree).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

ORIGIN = "https://alison.legislature.state.al.us"
ROW_SEP = "\u222b"  # ∫
FIELD_SEP = "\u2020"  # †
_SECTION_LABEL_RE = re.compile(
    r"^Section\s+([0-9]+[A-Za-z]?-[0-9]+[A-Za-z]?-[0-9A-Za-z.]+)\s*(.*)$"
)
_TITLE_LABEL_RE = re.compile(r"^Title\s+([0-9]+[A-Za-z]?)\s*(.*)$")
_CHAPTER_LABEL_RE = re.compile(r"^Chapter\s+([0-9]+[A-Za-z]?)\s*(.*)$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered|deleted)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_alabama_titles_blob(raw: str) -> List[Tuple[str, str]]:
    """Parse the official ``codeOfAlabamaTitles`` integral/dagger blob."""

    text = str(raw or "")
    if not text:
        return []
    if ROW_SEP not in text and FIELD_SEP not in text and len(text) > 2:
        field_sep, row_sep, text = text[0], text[1], text[2:]
    else:
        field_sep, row_sep = FIELD_SEP, ROW_SEP
    pairs: List[Tuple[str, str]] = []
    for row in text.lstrip(row_sep).split(row_sep):
        if not row:
            continue
        fields = row.split(field_sep)
        if len(fields) < 2:
            continue
        code_id, label = fields[0].strip(), fields[1].strip()
        if not code_id or code_id == "codeId":
            continue
        pairs.append((code_id, label))
    return pairs


def hierarchy_rows(raw: str) -> List[Tuple[str, str, str]]:
    """Title / Chapter / Section rows from the ALISON titles blob."""

    out: List[Tuple[str, str, str]] = []
    for _code_id, label in parse_alabama_titles_blob(raw):
        title = _TITLE_LABEL_RE.match(label)
        if title:
            out.append(("title", title.group(1), _clean(label)))
            continue
        chapter = _CHAPTER_LABEL_RE.match(label)
        if chapter:
            out.append(("chapter", chapter.group(1), _clean(label)))
            continue
        section = _SECTION_LABEL_RE.match(label)
        if section:
            out.append(("section", section.group(1), _clean(label)))
    return out


def parse_alabama_section_payload(
    item: dict,
    *,
    code_name: str = "Alabama Code",
) -> Optional[NormalizedStatute]:
    display_id = str(item.get("displayId") or "").strip()
    title = _clean(str(item.get("title") or ""))
    if not display_id:
        return None
    if _RESERVED.search(title) or _RESERVED.search(display_id):
        return None
    html_body = str(item.get("content") or "")
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html_body, "html.parser")
    paras = [_clean(para.get_text(" ")) for para in soup.find_all("p")]
    paras = [para for para in paras if para]
    if not paras:
        fallback = _clean(soup.get_text(" "))
        if fallback:
            paras = [fallback]
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(body[:160]):
        return None
    return NormalizedStatute(
        state_code="AL",
        state_name="Alabama",
        statute_id=f"{code_name} § {display_id}",
        code_name=code_name,
        section_number=display_id,
        section_name=(title or f"Section {display_id}")[:200],
        full_text=body[:14000],
        source_url=f"{ORIGIN}/code-of-alabama/?section={display_id}",
        official_cite=f"Ala. Code § {display_id}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_alison_graphql",
            "source_authority_class": "official",
            "discovery_method": "alison_codeOfAlabamaSection",
            "skip_hydrate": True,
        },
    )


def parse_alabama_titles_sections(
    raw: str,
    *,
    code_name: str = "Alabama Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Admit labeled Section rows from a titles blob (no body until JSON)."""

    statutes: List[NormalizedStatute] = []
    for _code_id, label in parse_alabama_titles_blob(raw):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        match = _SECTION_LABEL_RE.match(label)
        if not match:
            continue
        if _RESERVED.search(label):
            continue
        display_id = match.group(1)
        heading = _clean(match.group(2) or label)
        statutes.append(
            NormalizedStatute(
                state_code="AL",
                state_name="Alabama",
                statute_id=f"{code_name} § {display_id}",
                code_name=code_name,
                section_number=display_id,
                section_name=heading[:200] or f"Section {display_id}",
                full_text=heading[:14000],
                source_url=f"{ORIGIN}/code-of-alabama/?section={display_id}",
                official_cite=f"Ala. Code § {display_id}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_alison_titles_tree",
                    "source_authority_class": "official",
                    "discovery_method": "alison_codeOfAlabamaTitles",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def parse_configured_alabama(
    *,
    code_name: str = "Alabama Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    json_raw = str(os.environ.get("ALABAMA_SECTION_JSON") or "").strip()
    if json_raw:
        path = Path(json_raw).expanduser()
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else [payload]
            rows: List[NormalizedStatute] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                parsed = parse_alabama_section_payload(item, code_name=code_name)
                if parsed is not None:
                    rows.append(parsed)
                if max_statutes is not None and len(rows) >= int(max_statutes):
                    break
            if rows:
                return rows
    titles_raw = str(os.environ.get("ALABAMA_TITLES_TEXT") or "").strip()
    if titles_raw:
        path = Path(titles_raw).expanduser()
        if path.is_file():
            return parse_alabama_titles_sections(
                path.read_text(encoding="utf-8", errors="replace"),
                code_name=code_name,
                max_statutes=max_statutes,
            )
    return []
