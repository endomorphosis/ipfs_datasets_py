"""Official Missouri revisor chapter/section parsers.

Adapted from Vaquill-AI/open-us-law ``mo_bulk.parse`` (Apache-2.0).
Reads every table on OneChapter.aspx (not just the first).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://revisor.mo.gov/main"
_CHAPTER_RE = re.compile(r"OneChapter\.aspx\?chapter=([0-9][\w.]*)")
_CHAPTER_DOCUMENT_TITLE_RE = re.compile(
    r"^Missouri Revisor of Statutes - Revised Statutes of Missouri, "
    r"RSMo Chapter ([0-9]+[A-Za-z]?)$",
    re.IGNORECASE,
)
_CHAPTER_BODY_HEADING_RE = re.compile(
    r"^Chapter\s+([0-9]+[A-Za-z]?)\s+(.+)$",
    re.IGNORECASE,
)
_SECTION_NUMBER_PATTERN = (
    r"[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+(?:-[0-9A-Za-z]+)*)+"
)
_SECTION_NUMBER_RE = re.compile(rf"^{_SECTION_NUMBER_PATTERN}$")
_SECTION_RE = re.compile(rf"[?&]section=({_SECTION_NUMBER_PATTERN})(?:&|$)")
_SECTION_BODY_ID_RE = re.compile(
    rf"^\s*(?:\*+\s*)?({_SECTION_NUMBER_PATTERN})\b"
)
_SECTION_DOCUMENT_TITLE_RE = re.compile(
    rf"^Missouri Revisor of Statutes - Revised Statutes of Missouri, "
    rf"RSMo Section ({_SECTION_NUMBER_PATTERN})$",
    re.IGNORECASE,
)
_EFF_DATE_RE = re.compile(r"\s*\(\d{1,2}/\d{1,2}/\d{4}\)\s*$")
_EFF_DATE_CAPTURE_RE = re.compile(
    r"\s*\((?P<date>\d{1,2}/\d{1,2}/\d{4})\)\s*$"
)
_WS = re.compile(r"\s+")

_SOURCE_BOUND_EMPTY_CHAPTER_TERMINALS = {
    "152": ("Private Car Tax", "empty_chapter"),
    "203": (
        "Air Conservation (Transferred to Chapter 643)",
        "transferred",
    ),
    "255": (
        (
            "Division of Commerce and Industrial Development "
            "(Transferred to Chapter 625)"
        ),
        "transferred",
    ),
    "280": ("Treated Timber Products", "empty_chapter"),
    "312": ("Nonintoxicating Beer", "empty_chapter"),
    "318": ("Pool Tables", "empty_chapter"),
    "342": ("Stationary Engineers", "empty_chapter"),
    "460": ("Estates of Convicts", "empty_chapter"),
    "560": ("Fines", "empty_chapter"),
    "564": ("Inchoate Offenses", "empty_chapter"),
}


@dataclass(frozen=True)
class MissouriChapterSectionVariant:
    """One exact effective-dated Revisor ``PageSelect`` source record."""

    chapter_number: str
    section_number: str
    section_title: str
    effective_date: date
    effective_date_text: str
    source_url: str
    bid: str
    row_index: int
    terminal_disposition: str = ""


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("\xad", "")
    return _WS.sub(" ", text).strip()


def details_chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Home.aspx ``<details>`` chapter rows (``OneChapter.aspx?chapter=N``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    containers = soup.find_all("details") or [soup]
    for detail in containers:
        for anchor in detail.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            match = _CHAPTER_RE.search(href)
            if not match:
                continue
            number = match.group(1).strip()
            if not number or number in seen:
                continue
            seen.add(number)
            raw = _clean(anchor.get_text(" "))
            name = re.sub(rf"^\s*{re.escape(number)}\s*", "", raw).strip()
            out.append(
                (
                    number,
                    f"Chapter {number} {name}".strip(),
                    urljoin(base_url.rstrip("/") + "/", f"OneChapter.aspx?chapter={number}"),
                )
            )
    return out


def chapter_numbers(home_html: str) -> List[str]:
    seen = {match.group(1).strip() for match in _CHAPTER_RE.finditer(home_html or "")}

    def _key(token: str):
        try:
            return (0, int(token), token)
        except ValueError:
            return (1, 0, token)

    return sorted(seen, key=_key)


def chapter_page_identity(chapter_html: str) -> tuple[str, str] | None:
    """Return the exact chapter number/title visibly published by Revisor."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(chapter_html or "", "html.parser")
    document_title = _clean(soup.title.get_text(" ") if soup.title else "")
    title_match = _CHAPTER_DOCUMENT_TITLE_RE.fullmatch(document_title)
    if title_match is None or soup.body is None:
        return None

    visible_identities: set[tuple[str, str]] = set()
    for node in soup.body.find_all(string=True):
        parent_name = str(getattr(node.parent, "name", "") or "").lower()
        parent_classes = list(node.parent.get("class") or [])
        if parent_name != "div" or "lr-font-norm" not in parent_classes:
            continue
        match = _CHAPTER_BODY_HEADING_RE.fullmatch(_clean(str(node)))
        if match is None:
            continue
        visible_identities.add((match.group(1), _clean(match.group(2))))
    if len(visible_identities) != 1:
        return None
    chapter_number, chapter_title = visible_identities.pop()
    if title_match.group(1).casefold() != chapter_number.casefold():
        return None
    return chapter_number, chapter_title


def chapter_sections(chapter_html: str, chapter_number: str) -> List[Tuple[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(chapter_html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for row in soup.find_all("tr"):
        tds = row.find_all("td")
        if not tds:
            continue
        link = tds[0].find("a", href=True)
        if link is None:
            continue
        match = _SECTION_RE.search(str(link.get("href") or ""))
        if match:
            secnum = match.group(1).strip()
        else:
            txt = _clean(link.get_text())
            if _SECTION_NUMBER_RE.fullmatch(txt) is None:
                continue
            secnum = txt
        if secnum in seen or secnum.split(".")[0] != str(chapter_number):
            continue
        seen.add(secnum)
        title = _EFF_DATE_RE.sub("", _clean(tds[1].get_text()) if len(tds) > 1 else "").strip()
        out.append((secnum, title))
    return out


def _canonical_page_select_url(raw_href: str) -> tuple[str, str, str] | None:
    href = str(raw_href or "").strip()
    embedded_official = re.search(
        r"https://revisor\.mo\.gov/main/PageSelect\.aspx\?[^\s\"']+",
        href,
        flags=re.IGNORECASE,
    )
    if embedded_official is not None:
        href = embedded_official.group(0)
    absolute = urljoin(f"{BASE}/", href)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query, keep_blank_values=True)
    section_values = query.get("section") or []
    bid_values = query.get("bid") or []
    highlight_values = query.get("hl") or []
    if (
        parsed.scheme != "https"
        or parsed.hostname != "revisor.mo.gov"
        or parsed.path != "/main/PageSelect.aspx"
        or parsed.fragment
        or set(query) != {"section", "bid", "hl"}
        or len(section_values) != 1
        or len(bid_values) != 1
        or len(highlight_values) != 1
        or highlight_values[0] != ""
        or _SECTION_NUMBER_RE.fullmatch(section_values[0]) is None
        or re.fullmatch(r"[0-9]+", bid_values[0]) is None
    ):
        return None
    return absolute, section_values[0], bid_values[0]


def chapter_section_variants(
    chapter_html: str,
    chapter_number: str,
) -> list[MissouriChapterSectionVariant]:
    """Preserve every exact effective-dated ``PageSelect`` chapter row."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    requested = str(chapter_number or "").strip()
    soup = BeautifulSoup(chapter_html or "", "html.parser")
    variants: list[MissouriChapterSectionVariant] = []
    for row_index, row in enumerate(soup.find_all("tr")):
        if row.find_parent(id="BOTTOM") is not None:
            continue
        tds = row.find_all("td")
        if not tds:
            continue
        link = tds[0].find("a", href=True)
        if link is None:
            continue
        label = _clean(link.get_text(" "))
        if _SECTION_NUMBER_RE.fullmatch(label) is None:
            continue
        if len(tds) < 2:
            raise ValueError(
                f"Missouri chapter {requested} section row has no title cell: {label}"
            )
        source_identity = _canonical_page_select_url(str(link.get("href") or ""))
        if source_identity is None:
            raise ValueError(
                f"Missouri chapter {requested} has a noncanonical PageSelect row: {label}"
            )
        source_url, section_number, bid = source_identity
        if (
            label.casefold() != section_number.casefold()
            or section_number.split(".")[0].casefold() != requested.casefold()
        ):
            raise ValueError(
                "Missouri chapter row identity does not match its requested chapter: "
                f"chapter={requested} label={label} source={source_url}"
            )
        raw_title = _clean(tds[1].get_text(" "))
        effective_match = _EFF_DATE_CAPTURE_RE.search(raw_title)
        if effective_match is None:
            raise ValueError(
                f"Missouri chapter {requested} row lacks an effective date: {source_url}"
            )
        effective_date_text = effective_match.group("date")
        section_title = raw_title[: effective_match.start()].strip()
        if not section_title:
            raise ValueError(
                f"Missouri chapter {requested} row lacks a section title: {source_url}"
            )
        terminal_match = re.match(
            r"^\((repealed|transferred)\b",
            section_title,
            flags=re.IGNORECASE,
        )
        month, day, year = (
            int(part) for part in effective_date_text.split("/", maxsplit=2)
        )
        variants.append(
            MissouriChapterSectionVariant(
                chapter_number=requested,
                section_number=section_number,
                section_title=section_title,
                effective_date=date(year, month, day),
                effective_date_text=effective_date_text,
                source_url=source_url,
                bid=bid,
                row_index=row_index,
                terminal_disposition=(
                    terminal_match.group(1).lower() if terminal_match else ""
                ),
            )
        )
    return variants


def authoritative_chapter_section_variants(
    variants: list[MissouriChapterSectionVariant],
    *,
    as_of_date: date,
) -> tuple[
    list[MissouriChapterSectionVariant],
    list[MissouriChapterSectionVariant],
]:
    """Select the latest effective source record, with ``bid`` as tie-breaker."""

    grouped: dict[str, list[MissouriChapterSectionVariant]] = {}
    for variant in variants:
        grouped.setdefault(variant.section_number.casefold(), []).append(variant)

    selected: list[MissouriChapterSectionVariant] = []
    excluded: list[MissouriChapterSectionVariant] = []
    for records in grouped.values():
        eligible = [record for record in records if record.effective_date <= as_of_date]
        if not eligible:
            excluded.extend(records)
            continue
        authoritative = max(
            eligible,
            key=lambda record: (
                record.effective_date,
                int(record.bid),
                record.source_url,
            ),
        )
        selected.append(authoritative)
        excluded.extend(record for record in records if record is not authoritative)
    selected.sort(key=lambda record: record.row_index)
    excluded.sort(key=lambda record: record.row_index)
    return selected, excluded


def source_bound_empty_chapter_disposition(
    chapter_html: str,
    *,
    chapter_number: str,
    source_url: str,
) -> str | None:
    """Classify one exact current Revisor chapter with no statute rows."""

    requested = str(chapter_number or "").strip()
    expected = _SOURCE_BOUND_EMPTY_CHAPTER_TERMINALS.get(requested)
    if expected is None or source_url != f"{BASE}/OneChapter.aspx?chapter={requested}":
        return None
    identity = chapter_page_identity(chapter_html)
    if identity != (requested, expected[0]):
        return None
    if chapter_sections(chapter_html, requested):
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(chapter_html or "", "html.parser")
    section_links: list[tuple[str, str, bool]] = []
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" "))
        if (
            _SECTION_RE.search(raw_href) is None
            and _SECTION_NUMBER_RE.fullmatch(label) is None
        ):
            continue
        section_links.append(
            (
                urljoin(f"{BASE}/", raw_href),
                label,
                anchor.find_parent(id="BOTTOM") is not None,
            )
        )
    if section_links != [
        (
            "https://revisor.mo.gov/main/OneSection.aspx?section=3.090",
            "3.090",
            True,
        )
    ]:
        return None
    return expected[1]


def section_content(section_html: str) -> Tuple[List[str], str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], ""
    soup = BeautifulSoup(section_html or "", "html.parser")
    bottom = soup.find(id="BOTTOM")
    if bottom is None:
        return [], ""
    outer = bottom.find_previous_sibling()
    if outer is None:
        return [], ""
    first_child = outer.find(recursive=False)
    if first_child is None:
        return [], ""
    norm_div = first_child.find("div", class_="norm")
    if norm_div is None:
        return [], ""
    paras: List[str] = []
    history = ""
    for element in norm_div.find_all(recursive=False):
        classes = element.get("class", []) or []
        if element.name == "div" and "foot" in classes:
            history = re.sub(r"^[\-\xad\s]+", "", _clean(element.get_text(" "))).strip()
            continue
        if element.name == "p":
            text = _clean(element.get_text(" "))
            if text:
                paras.append(text)
    return paras, history


def section_body_identity(section_html: str) -> str:
    """Return the exact leading statutory identity from a Revisor body."""

    paras, _history = section_content(section_html)
    match = _SECTION_BODY_ID_RE.match(paras[0] if paras else "")
    return match.group(1).strip() if match is not None else ""


def section_page_identity(section_html: str) -> str:
    """Return a source-bound Revisor page identity even when its body is omitted.

    Some current ``PageSelect`` records publish an exact section/version shell but
    omit the operative text.  Require the independent document title, OpenGraph
    title, and canonical OpenGraph URL identities to agree before that shell can
    authorize a ``OneSection`` residual lookup.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(section_html or "", "html.parser")
    document_title = _clean(soup.title.get_text(" ") if soup.title else "")
    title_match = _SECTION_DOCUMENT_TITLE_RE.fullmatch(document_title)
    if title_match is None:
        return ""

    open_graph_title = soup.find(
        "meta",
        attrs={"property": re.compile(r"^og:title$", re.IGNORECASE)},
    )
    open_graph_url = soup.find(
        "meta",
        attrs={"property": re.compile(r"^og:url$", re.IGNORECASE)},
    )
    og_identity = _clean(str(open_graph_title.get("content") or "")) if open_graph_title else ""
    canonical_url = str(open_graph_url.get("content") or "").strip() if open_graph_url else ""
    parsed = urlparse(canonical_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    section_values = query.get("section") or []
    if (
        _SECTION_NUMBER_RE.fullmatch(og_identity) is None
        or parsed.scheme.casefold() != "https"
        or parsed.hostname != "revisor.mo.gov"
        or parsed.path.casefold() != "/main/onesection.aspx"
        or not set(query).issubset({"section", "bid"})
        or len(section_values) != 1
    ):
        return ""
    identities = {
        title_match.group(1).strip().casefold(),
        og_identity.casefold(),
        section_values[0].strip().casefold(),
    }
    return og_identity if len(identities) == 1 else ""


def section_url(section_number: str) -> str:
    return f"{BASE}/OneSection.aspx?section={section_number}"


def statute_from_section_html(
    html: str,
    *,
    section_number: str,
    code_name: str = "Missouri Revised Statutes",
    section_title: str = "",
    source_url: str = "",
    source_record_bid: str = "",
    effective_date: str = "",
    source_frontier_record_url: str = "",
    source_identity_fallback_reason: str = "",
) -> NormalizedStatute | None:
    paras, history = section_content(html)
    body = " ".join(paras).strip()
    if len(body) < 20:
        return None
    body_identity = _SECTION_BODY_ID_RE.match(paras[0] if paras else "")
    if (
        body_identity is None
        or body_identity.group(1).strip().casefold()
        != str(section_number or "").strip().casefold()
    ):
        return None
    exact_source_url = str(source_url or "").strip() or section_url(section_number)
    return NormalizedStatute(
        state_code="MO",
        state_name="Missouri",
        statute_id=f"{code_name} § {section_number}",
        code_name=code_name,
        section_number=section_number,
        section_name=(section_title or f"Section {section_number}")[:200],
        full_text=body,
        source_url=exact_source_url,
        official_cite=f"Mo. Rev. Stat. § {section_number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_missouri_revisor_html",
            "source_authority_class": "official",
            "discovery_method": "revisor_all_chapter_tables",
            "history": history,
            "source_record_id": exact_source_url,
            "source_record_bid": str(source_record_bid or "").strip(),
            "effective_date": str(effective_date or "").strip(),
            "source_frontier_record_url": str(
                source_frontier_record_url or exact_source_url
            ).strip(),
            "source_identity_fallback_reason": str(
                source_identity_fallback_reason or ""
            ).strip(),
            "skip_hydrate": True,
        },
    )


def configured_home_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MISSOURI_HOME_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_home_html() -> List[Tuple[str, str, str]]:
    path = configured_home_html_path()
    if path is None:
        return []
    return details_chapter_links(path.read_text(encoding="utf-8", errors="replace"))
