"""Official South Carolina chapter HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeSC.py`` (Apache-2.0).
Chapter pages are a flat ``#contentsection`` stream: bold
``SECTION X-Y-Z.`` headings, following text as body, ``HISTORY:`` terminator.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.scstatehouse.gov"
_SECTION_RE = re.compile(r"SECTION\s+([\w\-.]+?)\.", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_EXACT_TERMINAL = re.compile(
    r"^[\[(]?\s*(repealed|reserved|expired|renumbered|transferred|"
    r"omitted|deleted|recodified)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_south_carolina_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "South Carolina Code of Laws",
    title_number: str = "",
    chapter_number: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    heads = []
    for elem in content.find_all(["span", "strong", "b"]):
        text = _clean(elem.get_text(" "))
        match = _SECTION_RE.match(text)
        if match:
            heads.append((elem, match.group(1), text))
    statutes: List[NormalizedStatute] = []
    for index, (elem, number, heading) in enumerate(heads):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if _RESERVED.search(heading):
            continue
        stop = heads[index + 1][0] if index + 1 < len(heads) else None
        name_parts: List[str] = []
        body_parts: List[str] = []
        got_name = False
        sibling = elem.next_sibling
        while sibling is not None and sibling is not stop:
            if getattr(sibling, "name", None) in {"span", "strong", "b"}:
                break
            text = ""
            if isinstance(sibling, NavigableString):
                text = _clean(str(sibling))
            elif getattr(sibling, "name", None) not in {"br", "script", "style"}:
                text = _clean(sibling.get_text(" ") if hasattr(sibling, "get_text") else "")
            if text.upper().startswith("HISTORY:"):
                break
            if text:
                if not got_name:
                    name_parts.append(text)
                    got_name = True
                else:
                    body_parts.append(text)
            sibling = sibling.next_sibling
        name = _clean(" ".join(name_parts)) or f"Section {number}"
        body = _clean(" ".join(body_parts))
        if not body and name and not name.upper().startswith("SECTION"):
            body = name
        if _RESERVED.search(name) or len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="SC",
                state_name="South Carolina",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title_number or (parts[0] if parts else None),
                chapter_number=chapter_number or (parts[1] if len(parts) > 1 else None),
                section_number=number,
                section_name=name[:200],
                full_text=body,
                source_url=f"{source_url or BASE}#{number}",
                official_cite=f"S.C. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_south_carolina_code_html",
                    "source_authority_class": "official",
                    "discovery_method": "scstatehouse_contentsection_section",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def _exact_terminal_disposition(text: str) -> str:
    match = _EXACT_TERMINAL.match(_clean(text).strip(" ."))
    return str(match.group(1) or "").lower() if match else ""


def source_bound_empty_chapter_disposition(
    html: str,
    *,
    title_number: str,
    chapter_number: str,
) -> str:
    """Classify only an explicit source-marked empty chapter terminal."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    text = _clean(content.get_text(" "))
    title = str(int(str(title_number).strip()))
    chapter = str(int(str(chapter_number).strip()))
    if re.search(rf"\bTITLE\s+0*{re.escape(title)}\b", text, re.IGNORECASE) is None:
        return ""
    chapter_match = re.search(
        rf"\b(?:CHAPTER|ARTICLE)\s+0*{re.escape(chapter)}\b"
        r"(?P<tail>.{0,240})",
        text,
        re.IGNORECASE,
    )
    if chapter_match is None:
        return ""
    tail = str(chapter_match.group("tail") or "")
    if re.search(r"\[\s*repealed\s*\]", tail, re.IGNORECASE):
        return "repealed_chapter"
    if re.search(r"reserved\s+for\s+future\s+use", tail, re.IGNORECASE):
        return "reserved_chapter"
    return ""


def parse_south_carolina_chapter_html_strict(
    html: str,
    *,
    source_url: str,
    code_name: str,
    title_number: str,
    chapter_number: str,
) -> Tuple[List[NormalizedStatute], Dict[str, Any]]:
    """Close every source-bound section heading in one official chapter.

    The ordinary parser remains compatible with bounded callers.  This parser
    is reserved for the exact full-corpus frontier and classifies every source
    heading as operative, typed-terminal, or residual.  Concurrent effective
    versions are retained with distinct source-occurrence identities.
    """

    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError(
            "BeautifulSoup is required for strict South Carolina parsing"
        ) from exc

    expected_title = str(int(str(title_number).strip()))
    expected_chapter = str(int(str(chapter_number).strip()))
    expected_prefix = f"{expected_title}-{expected_chapter}-"
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    page_text = _clean(content.get_text(" "))
    page_identity_ok = bool(
        re.search(
            rf"\bTITLE\s+0*{re.escape(expected_title)}\b",
            page_text[:600],
            re.IGNORECASE,
        )
        and re.search(
            rf"\b(?:CHAPTER|ARTICLE)\s+0*{re.escape(expected_chapter)}\b",
            page_text[:900],
            re.IGNORECASE,
        )
    )

    markup_candidates: List[Tuple[Any, str, str]] = []
    for element in content.find_all(["span", "strong", "b"]):
        heading_text = _clean(element.get_text(" "))
        match = _SECTION_RE.match(heading_text)
        if match is not None:
            markup_candidates.append((element, match.group(1), heading_text))

    raw_candidates: List[Tuple[re.Match[str], str, str]] = []
    raw_text = ""
    if not markup_candidates:
        raw_text = content.get_text("\n", strip=True)
        raw_pattern = re.compile(
            r"(?mi)^\s*SECTION\s+"
            r"(?P<section>\d{1,3}-\d{1,3}-[0-9A-Za-z.-]+)\.\s*"
            r"(?P<heading>[^\n]*)$"
        )
        raw_candidates = [
            (match, str(match.group("section") or ""), _clean(match.group("heading")))
            for match in raw_pattern.finditer(raw_text)
        ]

    statutes: List[NormalizedStatute] = []
    terminal_dispositions: List[Dict[str, Any]] = []
    parser_residuals: List[Dict[str, Any]] = []
    occurrence_by_identity: Dict[str, int] = {}

    def _append_operative(
        *,
        number: str,
        heading: str,
        body: str,
        source_candidate_kind: str,
        source_order: int,
    ) -> None:
        identity_base = (
            f"sc:{expected_title}:{expected_chapter}:{number.casefold()}"
        )
        occurrence = occurrence_by_identity.get(identity_base, 0) + 1
        occurrence_by_identity[identity_base] = occurrence
        canonical_key = f"{identity_base}:occ-{occurrence}"
        statute_id = f"{code_name} § {number}"
        if occurrence > 1:
            statute_id += f" [source occurrence {occurrence}]"
        statutes.append(
            NormalizedStatute(
                state_code="SC",
                state_name="South Carolina",
                statute_id=statute_id,
                code_name=code_name,
                title_number=expected_title,
                chapter_number=expected_chapter,
                section_number=number,
                section_name=(heading or f"Section {number}")[:200],
                full_text=body,
                source_url=f"{source_url.rsplit('#', 1)[0]}#{number}",
                official_cite=f"S.C. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "canonical_section_key": canonical_key,
                    "discovery_method": "strict_scstatehouse_chapter_heading_frontier",
                    "skip_hydrate": True,
                    "source_authority_class": "official",
                    "source_candidate_kind": source_candidate_kind,
                    "source_kind": "official_south_carolina_code_html",
                    "source_occurrence": occurrence,
                    "source_order": source_order,
                    "strict_source_closure": True,
                },
            )
        )

    for index, (element, number, heading_text) in enumerate(markup_candidates):
        next_element = (
            markup_candidates[index + 1][0]
            if index + 1 < len(markup_candidates)
            else None
        )
        next_number = (
            markup_candidates[index + 1][1]
            if index + 1 < len(markup_candidates)
            else ""
        )
        pieces: List[str] = []
        sibling = element.next_sibling
        while sibling is not None and sibling is not next_element:
            if getattr(sibling, "name", None) in {"span", "strong", "b"}:
                break
            value = ""
            if isinstance(sibling, NavigableString):
                value = _clean(str(sibling))
            elif getattr(sibling, "name", None) not in {
                "br",
                "script",
                "style",
            }:
                value = _clean(
                    sibling.get_text(" ") if hasattr(sibling, "get_text") else ""
                )
            if value.upper().startswith("HISTORY:"):
                break
            if value:
                pieces.append(value)
            sibling = sibling.next_sibling

        heading = pieces[0] if pieces else ""
        body_parts = pieces[1:]
        disposition = _exact_terminal_disposition(heading)
        identity_matches = number.casefold().startswith(expected_prefix.casefold())
        if disposition:
            terminal_dispositions.append(
                {
                    "disposition": (
                        disposition
                        if identity_matches
                        else f"{disposition}_source_identity_mismatch"
                    ),
                    "heading": heading_text,
                    "section_number": number,
                    "source_candidate_kind": "markup_heading",
                    "source_order": index,
                }
            )
            continue
        if not identity_matches:
            parser_residuals.append(
                {
                    "heading": heading_text,
                    "reason": "chapter_section_identity_mismatch",
                    "section_number": number,
                    "source_order": index,
                }
            )
            continue
        if next_number.casefold() == number.casefold() and heading and not body_parts:
            terminal_dispositions.append(
                {
                    "disposition": "split_heading_container",
                    "heading": heading,
                    "section_number": number,
                    "source_candidate_kind": "markup_heading",
                    "source_order": index,
                }
            )
            continue
        body = _clean(" ".join(body_parts)) or heading
        if not body:
            parser_residuals.append(
                {
                    "heading": heading_text,
                    "reason": "empty_unclassified_section_body",
                    "section_number": number,
                    "source_order": index,
                }
            )
            continue
        _append_operative(
            number=number,
            heading=heading,
            body=body,
            source_candidate_kind="markup_heading",
            source_order=index,
        )

    for index, (match, number, heading) in enumerate(raw_candidates):
        end = (
            raw_candidates[index + 1][0].start()
            if index + 1 < len(raw_candidates)
            else len(raw_text)
        )
        body = _clean(raw_text[match.end() : end])
        disposition = _exact_terminal_disposition(heading)
        if disposition:
            terminal_dispositions.append(
                {
                    "disposition": disposition,
                    "heading": heading,
                    "section_number": number,
                    "source_candidate_kind": "unbolded_code_heading",
                    "source_order": index,
                }
            )
            continue
        if not number.casefold().startswith(expected_prefix.casefold()):
            parser_residuals.append(
                {
                    "heading": heading,
                    "reason": "chapter_section_identity_mismatch",
                    "section_number": number,
                    "source_order": index,
                }
            )
            continue
        if not body and not heading:
            parser_residuals.append(
                {
                    "heading": heading,
                    "reason": "empty_unclassified_section_body",
                    "section_number": number,
                    "source_order": index,
                }
            )
            continue
        _append_operative(
            number=number,
            heading=heading,
            body=body or heading,
            source_candidate_kind="unbolded_code_heading",
            source_order=index,
        )

    candidate_count = len(markup_candidates) + len(raw_candidates)
    chapter_disposition = ""
    if candidate_count == 0:
        chapter_disposition = source_bound_empty_chapter_disposition(
            html,
            title_number=expected_title,
            chapter_number=expected_chapter,
        )
        if not chapter_disposition:
            parser_residuals.append(
                {
                    "reason": "empty_chapter_without_source_terminal",
                    "source_url": source_url,
                }
            )
    if not page_identity_ok:
        parser_residuals.append(
            {
                "reason": "chapter_page_identity_mismatch",
                "source_url": source_url,
            }
        )

    report: Dict[str, Any] = {
        "candidate_sections": candidate_count,
        "chapter_disposition": chapter_disposition,
        "chapter_number": expected_chapter,
        "closed": (
            page_identity_ok
            and candidate_count
            == len(statutes) + len(terminal_dispositions) + len(parser_residuals)
            and not parser_residuals
        )
        if candidate_count
        else bool(page_identity_ok and chapter_disposition and not parser_residuals),
        "operative_sections": len(statutes),
        "parser_residuals": parser_residuals,
        "terminal_dispositions": terminal_dispositions,
        "terminal_sections": len(terminal_dispositions),
        "title_number": expected_title,
    }
    return statutes, report


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("SOUTH_CAROLINA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("SOUTH_CAROLINA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_links(path.read_text(encoding="utf-8", errors="replace"))


def title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Master TOC ``/code/titleN.php`` links."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = re.search(r"/code/title(\d+)\.php$", href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, urljoin(base_url, href)))
    return out


def chapter_rows(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Title-page ``CHAPTER N`` rows with ``/code/tNNcMMM.php`` HTML links."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in content.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = _clean(cells[0].get_text(" "))
        match = re.match(r"CHAPTER\s+([\w\-]+)", label, re.IGNORECASE)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        link = cells[1].find("a", href=True)
        if link is None:
            continue
        seen.add(number)
        out.append((number, label, urljoin(base_url, str(link.get("href") or ""))))
    return out
