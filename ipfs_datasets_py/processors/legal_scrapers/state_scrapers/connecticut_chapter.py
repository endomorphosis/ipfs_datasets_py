"""Official Connecticut chapter HTML parser (inline #sec_* siblings).

Adapted from Vaquill-AI/open-us-law ``scrapeCT.py`` (Apache-2.0).
Walk siblings from each ``#sec_*`` heading until ``nav_tbl``, the next
``toc_catchln`` / ``span.catchln``, or the next ``sec_*`` anchor.
``source-first`` / ``history-first`` paragraphs are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE_PUB = "https://www.cga.ct.gov/current/pub"
_RESERVED = re.compile(
    r"\((?:repealed|expired|reserved|renumbered|transferred)\s*\.?\s*\)",
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(r"^sec_([A-Za-z0-9][A-Za-z0-9._\-]*)$")
_GROUP_ANCHOR_RE = re.compile(
    r"^secs_([A-Za-z0-9][A-Za-z0-9._\-]*"
    r"(?:(?:_to_|_and_)[A-Za-z0-9][A-Za-z0-9._\-]*)+)$",
    re.IGNORECASE,
)
_SEC_ID_RE = re.compile(r"^sec_")
_WS = re.compile(r"\s+")
_HEADING_RE = re.compile(
    r"Sec\.\s*(?P<num>[A-Za-z0-9][A-Za-z0-9._\-]*)\.\s*(?P<head>.*)$",
    re.IGNORECASE,
)
_INACTIVE_HEADING = re.compile(
    r"^\(?\s*(?:repealed|expired|reserved|renumbered|transferred)\s*\.?\s*\)?$",
    re.IGNORECASE,
)
_INACTIVE_GROUP_DISPOSITION_RE = re.compile(
    r"(?:"
    r"\bare repealed\b.*\.\s*$"
    r"|\bTransferred to Chapter\b.*\.\s*$"
    r"|\bReserved for future use\s*\.\s*$"
    r"|\bObsolete\s*\.\s*$"
    r")",
    re.IGNORECASE,
)
# The retained official ``chap_319i.htm`` body (SHA-256
# 76a4e6ebe4ea419c0840baef209230806c0f8e2072f14eb5d9ba2603f29f7ca4)
# has one stale HTML locator: its TOC and catchline both publish active
# § 17a-615, while both link through ``sec_17a-175``.  The latter identity is
# already the genuine active Compact section in retained ``chap_319a.htm``
# (SHA-256 12600b721582c2ff8883527912383921b3849ac9a71db2e73ba057fc3bfecec2).
# Reconcile only the exact official source and complete retained introductory
# structure.  Any drift remains an identity conflict rather than silently
# assigning content to either statute.
_EXACT_STALE_ACTIVE_ANCHORS = {
    (
        "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        "sec_17a-175",
    ): {
        "section_number": "17a-615",
        "heading": (
            "Sec. 17a-615. (Formerly Sec. 17-258). "
            "Interstate Compact on Mental Health."
        ),
        "intro": (
            "Sec. 17a-615. (Formerly Sec. 17-258). "
            "Interstate Compact on Mental Health. The Interstate Compact on "
            "Mental Health is hereby enacted into law and entered into by "
            "this state with all other states legally joining therein in the "
            "form substantially as follows:"
        ),
    }
}


_TITLE_HREF_RE = re.compile(r"title_([0-9a-z]+)\.htm$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(r"chap_([0-9a-z]+)\.htm$", re.IGNORECASE)
_ARTICLE_HREF_RE = re.compile(r"art_([0-9a-z]+)\.htm$", re.IGNORECASE)


def _join_catalog_href(base_url: str, href: str) -> str:
    """Resolve a child beside an HTML page or beneath a directory base."""

    from urllib.parse import urlparse, urljoin

    parsed = urlparse(str(base_url or ""))
    base = str(base_url or "")
    if not parsed.path.endswith("/") and not re.search(
        r"\.html?$", parsed.path, re.IGNORECASE
    ):
        base = base.rstrip("/") + "/"
    return urljoin(base, href)


def titles_from_index(html: str, *, base_url: str = BASE_PUB) -> List[Tuple[str, str]]:
    """Title numbers and URLs from ``titles.htm`` (``toc_ttl_desig`` / title_N.htm)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1).lstrip("0") or match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((_join_catalog_href(base_url, href), number))
    return out


def chapters_from_title(html: str, *, base_url: str = BASE_PUB) -> List[Tuple[str, str]]:
    """Chapter/article URLs from an exact Connecticut title page.

    Most titles use ``chap_NNN.htm``.  Title 42a (the Uniform Commercial
    Code) uses the parallel official ``art_NNN.htm`` hierarchy instead.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    anchors = soup.find_all("a", class_="toc_ch_link") or soup.find_all("a", href=True)
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href) or _ARTICLE_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1).lstrip("0") or match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((_join_catalog_href(base_url, href), number))
    return out


def chapter_url(chapter: str) -> str:
    token = str(chapter or "").strip().lower().zfill(3)
    if token.isdigit():
        token = token.zfill(3)
    return f"{BASE_PUB}/chap_{token}.htm"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _anchor_number(anchor_id: str) -> Optional[str]:
    match = _ANCHOR_RE.match(str(anchor_id or "").strip())
    return match.group(1) if match else None


def _is_section_boundary(tag, current_id: str) -> bool:
    if tag.name == "table":
        return True
    classes = tag.get("class") or []
    if tag.name == "p" and "toc_catchln" in classes:
        return True
    if tag.find("span", class_="catchln"):
        nxt = tag.find(id=_SEC_ID_RE)
        if nxt is None or str(nxt.get("id") or "") != current_id:
            return True
    nxt = tag.find(id=_SEC_ID_RE) if tag.name == "p" else None
    return bool(nxt is not None and str(nxt.get("id") or "") != current_id)


def _heading_and_rest(text: str, section_number: str) -> Tuple[str, str]:
    match = _HEADING_RE.match(text)
    if match:
        return match.group("head").strip(" ."), ""
    prefix = f"Sec. {section_number}."
    if text.lower().startswith(prefix.lower()):
        rest = text[len(prefix) :].strip()
        return rest[:200], ""
    return text[:200], ""


def _is_inactive_section_heading(text: str) -> bool:
    cleaned = _clean(text)
    if _RESERVED.search(cleaned):
        return True
    match = _HEADING_RE.match(cleaned)
    disposition = match.group("head") if match else cleaned
    return bool(_INACTIVE_HEADING.fullmatch(disposition.strip()))


def _inactive_group_identity(span) -> Optional[str]:
    """Return a grouped-section identity only for an exact inactive group."""

    match = _GROUP_ANCHOR_RE.fullmatch(str(span.get("id") or "").strip())
    if match is None:
        return None
    parent = span.find_parent("p")
    if parent is None:
        return None
    text = _clean(parent.get_text(" "))
    if not re.match(r"^Secs?\.\s+", text, flags=re.IGNORECASE):
        return None
    if _INACTIVE_GROUP_DISPOSITION_RE.search(text) is None:
        return None
    return match.group(1)


def _reconciled_section_number(
    soup,
    *,
    chapter_url: str,
    anchor_id: str,
    anchor_number: str,
    anchor,
    toc,
    heading_text: str,
    toc_text: str,
) -> str:
    """Reconcile one exactly retained stale locator or reject the conflict."""

    visible_numbers = {
        match.group("num").casefold()
        for value in (heading_text, toc_text)
        if (match := _HEADING_RE.match(value)) is not None
    }
    if not visible_numbers or visible_numbers == {anchor_number.casefold()}:
        return anchor_number

    expected = _EXACT_STALE_ACTIVE_ANCHORS.get(
        (str(chapter_url or "").strip(), anchor_id)
    )
    expected_number = str((expected or {}).get("section_number") or "")
    exact_reconciliation = bool(
        expected
        and visible_numbers == {expected_number.casefold()}
        and heading_text == expected["heading"]
        and toc_text == expected["heading"]
        and anchor is not None
        and anchor.name == "span"
        and "catchln" in (anchor.get("class") or [])
        and anchor.parent is not None
        and anchor.parent.name == "p"
        and _clean(anchor.parent.get_text(" ")) == expected["intro"]
        and len(soup.find_all(id=anchor_id)) == 1
        and len(soup.find_all("a", href=f"#{anchor_id}")) == 1
        and soup.find(id=f"sec_{expected_number}") is None
    )
    if exact_reconciliation:
        return expected_number
    raise ValueError(
        "Connecticut section anchor/catchline identity conflict: "
        f"chapter_url={chapter_url} anchor_id={anchor_id} "
        f"anchor_number={anchor_number} visible_numbers={sorted(visible_numbers)}"
    )


def _section_frontier_from_soup(
    soup,
    *,
    chapter_url: str = "",
) -> List[dict]:
    anchors: List[str] = []
    toc_text_by_anchor: dict[str, str] = {}
    for para in soup.find_all("p", class_="toc_catchln"):
        link = para.find("a", href=True)
        href = str(link.get("href") or "") if link else ""
        toc_text = _clean(para.get_text(" "))
        if href.startswith("#"):
            anchor_id = href.lstrip("#")
            anchors.append(anchor_id)
            toc_text_by_anchor[anchor_id] = toc_text
            continue
        match = _HEADING_RE.match(toc_text)
        if match:
            anchor_id = f"sec_{match.group('num')}"
            anchors.append(anchor_id)
            toc_text_by_anchor[anchor_id] = toc_text
    for span in soup.select("span.catchln[id^='sec_'], span[id^='sec_']"):
        anchors.append(str(span.get("id") or ""))

    out: List[dict] = []
    seen: set[str] = set()
    for anchor_id in anchors:
        anchor_number = _anchor_number(anchor_id)
        if not anchor_number:
            continue
        anchor = soup.find(id=anchor_id)
        toc = soup.find("a", href=f"#{anchor_id}")
        heading_text = _clean(anchor.get_text(" ")) if anchor is not None else ""
        toc_text = (
            _clean(toc.get_text(" "))
            if toc is not None
            else toc_text_by_anchor.get(anchor_id, "")
        )
        number = _reconciled_section_number(
            soup,
            chapter_url=chapter_url,
            anchor_id=anchor_id,
            anchor_number=anchor_number,
            anchor=anchor,
            toc=toc,
            heading_text=heading_text,
            toc_text=toc_text,
        )
        if number in seen:
            continue
        seen.add(number)
        inactive = bool(
            _is_inactive_section_heading(heading_text)
            or _is_inactive_section_heading(toc_text)
        )
        out.append(
            {
                "anchor_id": anchor_id,
                "disposition": "inactive" if inactive else "active",
                "section_number": number,
            }
        )
    for span in soup.select("span.catchln[id^='secs_'], span[id^='secs_']"):
        identity = _inactive_group_identity(span)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        out.append(
            {
                "anchor_id": str(span.get("id") or ""),
                "disposition": "inactive",
                "section_number": identity,
            }
        )
    return out


def connecticut_section_frontier(
    html: str,
    *,
    chapter_url: str = "",
) -> List[dict]:
    """Return the exact active/inactive section frontier used by the parser."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    return _section_frontier_from_soup(
        BeautifulSoup(html or "", "html.parser"),
        chapter_url=chapter_url,
    )


def parse_connecticut_chapter_html(
    html: str,
    *,
    chapter_url: str = "",
    code_name: str = "Connecticut General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse inline CGA chapter sections from one ``chap_NNN.htm`` page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    source = chapter_url or BASE_PUB
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()

    for frontier_row in _section_frontier_from_soup(
        soup,
        chapter_url=chapter_url,
    ):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if frontier_row["disposition"] != "active":
            continue
        anchor_id = str(frontier_row["anchor_id"])
        number = str(frontier_row["section_number"])
        if number in seen:
            continue
        anchor = soup.find(id=anchor_id)
        if anchor is None:
            continue
        heading_tag = anchor.parent
        heading_text = _clean(anchor.get_text(" "))
        toc = soup.find("a", href=f"#{anchor_id}")
        toc_text = _clean(toc.get_text(" ")) if toc else ""
        name, _ = _heading_and_rest(heading_text or toc_text, number)
        if _RESERVED.search(name):
            continue

        body_parts: List[str] = []
        heading_full = _clean(heading_tag.get_text(" ")) if heading_tag is not None else heading_text
        leftover = heading_full
        for prefix in (heading_text, f"Sec. {number}. {name}", f"Sec. {number}."):
            if leftover.lower().startswith(prefix.lower()):
                leftover = leftover[len(prefix) :].strip(" .")
                break
        if leftover and not _RESERVED.search(leftover):
            body_parts.append(leftover)

        sibling = heading_tag.next_sibling if heading_tag is not None else None
        while sibling is not None:
            if getattr(sibling, "name", None):
                if _is_section_boundary(sibling, anchor_id):
                    break
                classes = sibling.get("class") or []
                raw = _clean(sibling.get_text(" "))
                if raw and not any(cls in ("source-first", "history-first") for cls in classes):
                    body_parts.append(raw)
            sibling = sibling.next_sibling

        body = _clean(" ".join(body_parts))
        if not body:
            continue
        seen.add(number)
        statutes.append(
            NormalizedStatute(
                state_code="CT",
                state_name="Connecticut",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                section_number=number,
                section_name=(name or f"Section {number}")[:200],
                full_text=body,
                source_url=f"{source}#{anchor_id}",
                official_cite=f"Conn. Gen. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_connecticut_chapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "cga_sec_sibling_walk",
                    "chapter_url": source,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CONNECTICUT_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_titles_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CONNECTICUT_TITLES_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_titles_html() -> List[Tuple[str, str]]:
    path = configured_titles_html_path()
    if path is None:
        return []
    return titles_from_index(path.read_text(encoding="utf-8", errors="replace"))
