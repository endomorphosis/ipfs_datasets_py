"""Official Wisconsin statutes viewer parser.

Adapted from Vaquill-AI/open-us-law ``wi_bulk.parse`` (Apache-2.0).
``docs.legis.wisconsin.gov`` renders a section as the flat run of
``div.qsatxt_*`` blocks sharing ``data-section``. Case annotations in
``qsnote_*`` siblings (except history) are dropped.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://docs.legis.wisconsin.gov"
_WS_RE = re.compile(r"\s+")
_SEC_ANCHOR_RE = re.compile(r"/document/statutes/(\d+\.\d+\w*)(?:[/#?]|$)")
_TOC_LEAD_SECTION_RE = re.compile(r"^(\d+\.\d+\w*)\b")
_HIST_LEAD_RE = re.compile(r"^\s*[\d.]+\w*\s+History\s+History:\s*", re.IGNORECASE)
_RESERVED_KEYWORDS = ("[repealed]", "[reserved]", "[expired]", "(repealed)", "(reserved)")


@dataclass(frozen=True)
class WisconsinChapterFrontierWindow:
    """One retained viewer window while the chapter TOC is being exhausted."""

    chapter_number: str
    section_rows: Tuple[Tuple[str, str, str], ...]
    body_started: bool
    next_url: str
    terminal_disposition: str
    residuals: Tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class WisconsinSectionWindow:
    """Source-bound blocks for one requested section in one viewer window."""

    section_number: str
    encountered_sections: Tuple[str, ...]
    blocks: Tuple[Tuple[str, str], ...]
    title: str
    terminal_disposition: str
    next_url: str
    target_seen: bool
    target_complete: bool
    residuals: Tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class WisconsinSectionParseResult:
    """Exact one-candidate parser algebra for a section viewer traversal."""

    section_number: str
    statute: Optional[NormalizedStatute]
    terminal_section: Optional[Mapping[str, str]]
    residuals: Tuple[Mapping[str, str], ...]
    source_block_count: int
    closed: bool


def chapter_of(section_number: str) -> str:
    token = str(section_number or "").strip()
    return token.split(".", 1)[0]


def section_url(section_number: str) -> str:
    return f"{BASE}/document/statutes/{section_number}"


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("\u2009", " ").replace("\u200b", "")
    return _WS_RE.sub(" ", text).strip()


def _is_qsatxt(cls_list) -> bool:
    return any(str(item).startswith("qsatxt_") for item in (cls_list or []))


def _terminal_disposition(text: str) -> str:
    folded = _clean(text).casefold()
    if "[repealed]" in folded or "(repealed)" in folded:
        return "repealed"
    if "[reserved]" in folded or "(reserved)" in folded:
        return "reserved"
    if "[expired]" in folded or "(expired)" in folded:
        return "expired"
    if "[renumbered]" in folded or "(renumbered)" in folded:
        return "renumbered"
    return ""


def _viewer_down_url(soup, *, page_url: str) -> str:
    for anchor in soup.select(".navigation a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" ")).casefold()
        if label == "down" or re.search(r"(?:[?&])down=1(?:&|$)", href):
            return urljoin(page_url or BASE, href)
    return ""


def parse_wisconsin_chapter_frontier_window(
    html: str,
    *,
    chapter: str,
    page_url: str,
) -> WisconsinChapterFrontierWindow:
    """Parse only the official chapter TOC run from one retained viewer window.

    The viewer is a bounded sliding window.  Large chapter TOCs therefore
    require following its source-derived ``Down`` links until statutory body
    blocks begin.  Ordinary citations in body text are deliberately excluded;
    only ``qstoc_entry`` links are frontier members.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return WisconsinChapterFrontierWindow(
            str(chapter), (), False, "", "", ({"reason": "beautifulsoup_unavailable"},)
        )
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    chapter_token = str(chapter or "").strip()
    rows: List[Tuple[str, str, str]] = []
    seen: Set[str] = set()
    residuals: List[Mapping[str, str]] = []
    for node in doc.find_all("div"):
        classes = {str(item) for item in (node.get("class") or [])}
        if "qstoc_entry" not in classes:
            continue
        label = _clean(node.get_text(" "))
        lead_match = _TOC_LEAD_SECTION_RE.match(label)
        lead_section = lead_match.group(1) if lead_match else ""
        if lead_section and chapter_of(lead_section) != chapter_token:
            lead_section = ""
        candidates: List[str] = []
        for anchor in node.find_all("a", href=True):
            match = _SEC_ANCHOR_RE.search(str(anchor.get("href") or ""))
            if match and chapter_of(match.group(1)) == chapter_token:
                candidates.append(match.group(1))
        candidate_sections = list(dict.fromkeys(candidates))
        if lead_section:
            # The leading TOC token is the source identity.  Later links in a
            # title are ordinary cross-references, and some operative source
            # rows (for example s. 854.30 in the retained 2023-24 viewer) omit
            # the self-link while still exposing an exact section identity.
            if candidate_sections and lead_section not in candidate_sections:
                residuals.append(
                    {
                        "reason": "toc_entry_leading_section_link_mismatch",
                        "chapter_number": chapter_token,
                        "section_number": lead_section,
                        "source_url": str(page_url or ""),
                    }
                )
                continue
            section = lead_section
        elif len(candidate_sections) == 1:
            section = candidate_sections[0]
        else:
            residuals.append(
                {
                    "reason": "toc_entry_without_exact_section_link",
                    "chapter_number": chapter_token,
                    "source_url": str(page_url or ""),
                }
            )
            continue
        if section in seen:
            residuals.append(
                {
                    "reason": "duplicate_section_in_toc_window",
                    "section_number": section,
                    "source_url": str(page_url or ""),
                }
            )
            continue
        seen.add(section)
        rows.append((section, label, section_url(section)))

    body_nodes = [
        node
        for node in doc.find_all("div")
        if _is_qsatxt(node.get("class") or [])
        and chapter_of(str(node.get("data-section") or "")) == chapter_token
    ]
    if rows and body_nodes:
        first_body = min(getattr(node, "sourceline", 0) or 0 for node in body_nodes)
        toc_lines = [
            getattr(node, "sourceline", 0) or 0
            for node in doc.find_all("div", class_="qstoc_entry")
        ]
        if first_body and any(line and line > first_body for line in toc_lines):
            residuals.append(
                {
                    "reason": "toc_entry_after_statutory_body_started",
                    "chapter_number": chapter_token,
                    "source_url": str(page_url or ""),
                }
            )

    page_text = _clean(doc.get_text(" "))
    terminal = ""
    if not rows and not body_nodes:
        terminal = _terminal_disposition(page_text)
    return WisconsinChapterFrontierWindow(
        chapter_number=chapter_token,
        section_rows=tuple(rows),
        body_started=bool(body_nodes),
        next_url=_viewer_down_url(soup, page_url=page_url),
        terminal_disposition=terminal,
        residuals=tuple(residuals),
    )


def parse_wisconsin_section_window(
    html: str,
    *,
    section_number: str,
    page_url: str,
) -> WisconsinSectionWindow:
    """Project one requested section from one official sliding viewer window."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return WisconsinSectionWindow(
            str(section_number), (), (), "", "", "", False, False,
            ({"reason": "beautifulsoup_unavailable"},),
        )
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    target = str(section_number or "").strip()
    encountered: List[str] = []
    blocks: List[Tuple[str, str]] = []
    title = ""
    residuals: List[Mapping[str, str]] = []
    target_index = -1
    later_other = False
    seen_block_ids: Dict[str, str] = {}
    for node in doc.find_all("div"):
        if not _is_qsatxt(node.get("class") or []):
            continue
        section = str(node.get("data-section") or "").strip()
        if section and section not in encountered:
            encountered.append(section)
        if section != target:
            if target_index >= 0:
                later_other = True
            continue
        if target_index < 0:
            target_index = len(encountered) - 1
        node_copy = copy.copy(node)
        title_span = node_copy.find("span", class_="qstitle_sect")
        if title_span is not None:
            candidate_title = _clean(title_span.get_text(" "))
            if candidate_title and title and candidate_title != title:
                residuals.append(
                    {
                        "reason": "conflicting_section_titles_in_window",
                        "section_number": target,
                        "source_url": str(page_url or ""),
                    }
                )
            elif candidate_title:
                title = candidate_title
        for span in node_copy.find_all("span", class_="qsnum_sect"):
            span.decompose()
        for span in node_copy.find_all("span", class_="qstitle_sect"):
            span.decompose()
        for anchor in node_copy.find_all("a", class_="reference"):
            anchor.decompose()
        text = _clean(node_copy.get_text(" "))
        identity = str(node.get("data-path") or "").strip()
        if not identity:
            identity = "sha256:" + hashlib.sha256(
                f"{target}\0{text}".encode("utf-8")
            ).hexdigest()
        previous = seen_block_ids.get(identity)
        if previous is not None:
            if previous != text:
                residuals.append(
                    {
                        "reason": "conflicting_repeated_section_block",
                        "section_number": target,
                        "block_identity": identity,
                    }
                )
            continue
        seen_block_ids[identity] = text
        if text:
            blocks.append((identity, text))

    next_url = _viewer_down_url(soup, page_url=page_url)
    target_seen = target_index >= 0
    terminal = _terminal_disposition(f"{title} {' '.join(text for _, text in blocks)}")
    target_complete = bool(
        target_seen and (terminal or later_other or not next_url)
    )
    return WisconsinSectionWindow(
        section_number=target,
        encountered_sections=tuple(encountered),
        blocks=tuple(blocks),
        title=title,
        terminal_disposition=terminal,
        next_url=next_url,
        target_seen=target_seen,
        target_complete=target_complete,
        residuals=tuple(residuals),
    )


def close_wisconsin_section_windows(
    windows: Sequence[WisconsinSectionWindow],
    *,
    section_number: str,
    code_name: str = "Wisconsin Statutes",
    source_url: str = "",
    traversal_closed: bool,
) -> WisconsinSectionParseResult:
    """Reconcile one source candidate as operative, terminal, or residual."""

    target = str(section_number or "").strip()
    residuals: List[Mapping[str, str]] = []
    blocks: Dict[str, str] = {}
    title = ""
    terminal = ""
    for window in windows:
        if window.section_number != target:
            residuals.append(
                {"reason": "window_changed_section_identity", "section_number": target}
            )
            continue
        residuals.extend(window.residuals)
        if window.title:
            if title and title != window.title:
                residuals.append(
                    {"reason": "conflicting_section_titles", "section_number": target}
                )
            else:
                title = window.title
        if window.terminal_disposition:
            if terminal and terminal != window.terminal_disposition:
                residuals.append(
                    {"reason": "conflicting_terminal_dispositions", "section_number": target}
                )
            terminal = window.terminal_disposition
        for identity, text in window.blocks:
            previous = blocks.get(identity)
            if previous is not None and previous != text:
                residuals.append(
                    {
                        "reason": "conflicting_replayed_section_block",
                        "section_number": target,
                        "block_identity": identity,
                    }
                )
            else:
                blocks.setdefault(identity, text)
    if not windows or not windows[0].target_seen:
        residuals.append({"reason": "requested_section_not_rendered", "section_number": target})
    if not traversal_closed:
        residuals.append({"reason": "section_viewer_traversal_not_closed", "section_number": target})
    if residuals:
        return WisconsinSectionParseResult(target, None, None, tuple(residuals), len(blocks), False)
    if terminal:
        return WisconsinSectionParseResult(
            target,
            None,
            {
                "section_number": target,
                "disposition": terminal,
                "source_url": source_url or section_url(target),
            },
            (),
            len(blocks),
            True,
        )
    body = _clean(" ".join(blocks.values()))
    if not body:
        return WisconsinSectionParseResult(
            target,
            None,
            None,
            ({"reason": "operative_section_body_missing", "section_number": target},),
            len(blocks),
            False,
        )
    chapter = chapter_of(target)
    statute = NormalizedStatute(
        state_code="WI",
        state_name="Wisconsin",
        statute_id=f"{code_name} § {target}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=target,
        section_name=(title or f"Section {target}")[:200],
        full_text=body,
        source_url=source_url or section_url(target),
        official_cite=f"Wis. Stat. § {target}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_wisconsin_qsatxt",
            "source_authority_class": "official",
            "discovery_method": "official_chapter_toc_plural_viewer_frontier",
            "skip_hydrate": True,
        },
    )
    return WisconsinSectionParseResult(target, statute, None, (), len(blocks), True)


def section_anchors(html: str, chapter: Optional[str] = None) -> Set[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return set()
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    out: Set[str] = set()
    for anchor in doc.find_all("a", href=True):
        match = _SEC_ANCHOR_RE.search(str(anchor.get("href") or ""))
        if not match:
            continue
        sec = match.group(1)
        if chapter is not None and chapter_of(sec) != str(chapter):
            continue
        out.add(sec)
    return out


def parse_page(html: str, chapter: str) -> Tuple[List[str], Dict[str, dict]]:
    """Harvest fully rendered ``qsatxt_*`` bodies for one chapter on a viewer page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], {}
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    ordered: List[str] = []
    seen: Set[str] = set()
    paras_by_sec: Dict[str, List[str]] = {}
    title_by_sec: Dict[str, str] = {}
    chapter_token = str(chapter or "")

    for div in doc.find_all("div"):
        cls = div.get("class") or []
        if not _is_qsatxt(cls):
            continue
        sec = str(div.get("data-section") or "").strip()
        if not sec or chapter_of(sec) != chapter_token:
            continue
        if sec not in seen:
            seen.add(sec)
            ordered.append(sec)
        div_copy = copy.copy(div)
        title_span = div_copy.find("span", class_="qstitle_sect")
        if title_span is not None and sec not in title_by_sec:
            title_by_sec[sec] = _clean(title_span.get_text(" "))
        for span in div_copy.find_all("span", class_="qsnum_sect"):
            span.decompose()
        for span in div_copy.find_all("span", class_="qstitle_sect"):
            span.decompose()
        for anchor in div_copy.find_all("a", class_="reference"):
            anchor.decompose()
        text = _clean(div_copy.get_text(" "))
        if text:
            paras_by_sec.setdefault(sec, []).append(text)

    hist_by_sec: Dict[str, str] = {}
    for div in doc.find_all("div", class_="qsnote_history"):
        sec = str(div.get("data-section") or "").strip()
        if not sec or chapter_of(sec) != chapter_token:
            continue
        raw = _HIST_LEAD_RE.sub("", _clean(div.get_text(" "))).strip()
        if raw:
            hist_by_sec[sec] = (hist_by_sec.get(sec, "") + " " + raw).strip()

    sections: Dict[str, dict] = {}
    for sec in ordered:
        paras = paras_by_sec.get(sec, [])
        title = title_by_sec.get(sec, "")
        blob = f"{title} {' '.join(paras)}".lower()
        status = None
        for keyword in _RESERVED_KEYWORDS:
            if keyword in blob:
                status = "repealed" if "repeal" in keyword else "reserved"
                break
        sections[sec] = {
            "title": title,
            "paragraphs": paras,
            "history": hist_by_sec.get(sec, ""),
            "status": status,
        }
    return ordered, sections


def statutes_from_page(
    html: str,
    *,
    chapter: str,
    code_name: str = "Wisconsin Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    ordered, sections = parse_page(html, chapter)
    out: List[NormalizedStatute] = []
    for sec in ordered:
        if max_statutes is not None and len(out) >= int(max_statutes):
            break
        data = sections.get(sec) or {}
        if data.get("status"):
            continue
        body = " ".join(data.get("paragraphs") or []).strip()
        if len(body) < 40:
            continue
        out.append(
            NormalizedStatute(
                state_code="WI",
                state_name="Wisconsin",
                statute_id=f"{code_name} § {sec}",
                code_name=code_name,
                chapter_number=chapter,
                section_number=sec,
                section_name=(data.get("title") or f"Section {sec}")[:200],
                full_text=body,
                source_url=section_url(sec),
                official_cite=f"Wis. Stat. § {sec}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wisconsin_qsatxt",
                    "source_authority_class": "official",
                    "discovery_method": "docs_legis_qsatxt_window",
                    "skip_hydrate": True,
                },
            )
        )
    return out


_CHAPTER_TOC_RE = re.compile(r"/document/statutes/(\d+)$")


def toc_chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """TOC ``/document/statutes/N`` chapter rows (not section ``N.NN``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for paragraph in soup.find_all("p"):
        anchor = None
        for candidate in paragraph.find_all("a", href=True):
            href = str(candidate.get("href") or "").strip()
            if _CHAPTER_TOC_RE.search(href):
                anchor = candidate
                break
        if anchor is None:
            continue
        match = _CHAPTER_TOC_RE.search(str(anchor.get("href") or ""))
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        name = _clean(paragraph.get_text(" "))
        name = re.sub(r"\(PDF:[^)]*\)", "", name)
        name = _clean(name).strip(" -")
        out.append((number, name or f"Chapter {number}", urljoin(base_url, f"/document/statutes/{number}")))
    return out


_PDF_HEADER_RE = re.compile(
    r"updated|published and certified|electronically scanned|wis\. stats?\.",
    re.IGNORECASE,
)


def pdf_front_toc_sections(pdf_text: str, chapter: str) -> Set[str]:
    """Current sections from a chapter PDF's front TOC (before first ``History:``).

    Local dump only; PDFs are never auto-downloaded here.
    """

    text = pdf_text or ""
    cut = text.lower().find("history:")
    region = text[:cut] if cut != -1 else text
    out: Set[str] = set()
    for line in region.splitlines():
        if _PDF_HEADER_RE.search(line):
            continue
        for match in re.finditer(r"\b(\d+\.\d+\w*)\b", line):
            sec = match.group(1)
            if chapter_of(sec) == str(chapter):
                out.add(sec)
    return out


def configured_chapter_pdf_text_path() -> Optional[Path]:
    raw = str(os.environ.get("WISCONSIN_CHAPTER_PDF_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_chapter_pdf_toc(chapter: str) -> Set[str]:
    """Local extracted chapter-PDF text. PDFs are never auto-downloaded."""

    path = configured_chapter_pdf_text_path()
    if path is None:
        return set()
    return pdf_front_toc_sections(
        path.read_text(encoding="utf-8", errors="replace"),
        chapter,
    )


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WISCONSIN_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return toc_chapter_links(path.read_text(encoding="utf-8", errors="replace"))
