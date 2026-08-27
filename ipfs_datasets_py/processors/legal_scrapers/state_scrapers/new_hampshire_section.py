"""Official New Hampshire RSA section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNH.py`` (Apache-2.0).
Body lives in ``<codesect>``; ``<sourcenote>`` history is dropped.
"""

from __future__ import annotations

import os
import re
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://gc.nh.gov/rsa/html"
NHTOC_BASE = f"{BASE}/NHTOC"
_WS = re.compile(r"\s+")
_TITLE_HREF_RE = re.compile(r"NHTOC/NHTOC-([A-Z][A-Z\-]*)\.htm$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"^NHTOC-[A-Z][A-Z\-]*-[\dA-Z][\w\-]*\.htm$",
    re.IGNORECASE,
)
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€")
_CP1252_FIX = {
    "\u0080": "€",
    "\u0082": "‚",
    "\u0083": "ƒ",
    "\u0084": "„",
    "\u0085": "…",
    "\u0091": "‘",
    "\u0092": "’",
    "\u0093": "“",
    "\u0094": "”",
    "\u0096": "–",
    "\u0097": "—",
    "\u0099": "™",
}
_TITLE_LABEL_RE = re.compile(
    r"^TITLE\s+(?P<number>[IVXLCDM]+(?:-[A-Z]+)?)\s*:\s*(?P<name>.+)$",
    re.IGNORECASE,
)
_CHAPTER_LABEL_RE = re.compile(
    r"^CHAPTER\s+(?P<number>[0-9]+(?:-[A-Z0-9]+)*)\s*:\s*(?P<name>.+)$",
    re.IGNORECASE,
)
_SECTION_LABEL_RE = re.compile(
    r"^Section\s*:?\s*(?P<number>[0-9]+(?:-[A-Z0-9]+)*:[0-9A-Z][0-9A-Z.\-]*)"
    r"(?:\s+(?P<name>.*))?$",
    re.IGNORECASE,
)
_TERMINAL_PREFIX_RE = re.compile(
    r"^\[?(?P<kind>repealed|expired|reserved|omitted|deleted|renumbered|transferred|recodified)\]?"
    r"(?:\.|$|\s+(?:by|effective|as\b|to\b).*)",
    re.IGNORECASE,
)
_BRACKETED_TERMINAL_RE = re.compile(
    r"^\[(?P<kind>repealed|expired|reserved|omitted|deleted|renumbered|transferred|recodified)\.?\]$",
    re.IGNORECASE,
)
_ROOT_REPEALED_TITLE_RE = re.compile(
    r"^\(?Entire\s+Title\s+Was\s+Repealed"
    r"(?:\s*-\s*Chapters?\s+[0-9A-Z-]+\s*-\s*[0-9A-Z-]+)?\)?$",
    re.IGNORECASE,
)


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    value = unescape(text or "")
    for src, dest in _CP1252_FIX.items():
        if src in value:
            value = value.replace(src, dest)
    value = _fix_encoding(value.replace("\xa0", " "))
    return _WS.sub(" ", value).strip()


def _canonical_source_url(base_url: str, href: str) -> str:
    """Resolve an RSA href, unwrapping a Wayback-rewritten original URL."""

    resolved = urljoin(base_url, str(href or "").strip())
    for candidate in (str(href or "").strip(), resolved):
        match = re.search(
            r"(?:^|/)web/\d+(?:[a-z_]+)?/(https?:/{1,2}.+)$",
            candidate,
            flags=re.IGNORECASE,
        )
        if match is None:
            continue
        original = str(match.group(1) or "").strip()
        original = re.sub(r"^(https?):/([^/])", r"\1://\2", original)
        if original:
            return original
    return resolved


def terminal_disposition_from_label(text: str) -> Optional[str]:
    """Return a terminal disposition only for an exact operative-status label."""

    value = _clean(text).strip()
    bracketed = _BRACKETED_TERMINAL_RE.fullmatch(value)
    if bracketed:
        return str(bracketed.group("kind") or "").lower()
    value = value.rstrip(".").strip()
    match = _TERMINAL_PREFIX_RE.fullmatch(value)
    return str(match.group("kind") or "").lower() if match else None


def section_citation_from_url(source_url: str) -> str:
    """Derive ``chapter:section`` from one exact official RSA locator."""

    value = _canonical_source_url(BASE, str(source_url or "").strip())
    try:
        path = urlparse(value).path
    except Exception:
        return ""
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or not parts[-1].lower().endswith(".htm"):
        return ""
    chapter = parts[-2].strip()
    stem = parts[-1][:-4].strip()
    prefix = f"{chapter}-"
    if not chapter or not stem.lower().startswith(prefix.lower()):
        return ""
    suffix = stem[len(prefix) :].strip()
    return f"{chapter}:{suffix}" if suffix else ""


def nhtoc_title_units(html: str, *, base_url: str = BASE) -> List[Dict[str, str]]:
    """Return the source-ordered, identity-checked root title frontier."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    units: List[Dict[str, str]] = []
    seen_numbers: set[str] = set()
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().replace("\\", "/")
        href_match = _TITLE_HREF_RE.search(href)
        if href_match is None:
            continue
        number = href_match.group(1).upper()
        label = _clean(anchor.get_text(" "))
        label_match = _TITLE_LABEL_RE.fullmatch(label)
        if label_match is None or label_match.group("number").upper() != number:
            raise ValueError(
                f"New Hampshire title label does not match its locator: {href!r}"
            )
        source_url = _canonical_source_url(base_url, href)
        key = source_url.casefold()
        if number.casefold() in seen_numbers or key in seen_urls:
            raise ValueError(
                f"New Hampshire root contains a duplicate title identity: {number}"
            )
        seen_numbers.add(number.casefold())
        seen_urls.add(key)

        note = ""
        list_item = anchor.find_parent("li")
        sibling = list_item.find_next_sibling() if list_item is not None else None
        if sibling is not None and "chapter_list" in {
            str(item).casefold() for item in (sibling.get("class") or [])
        }:
            note = _clean(sibling.get_text(" "))
        terminal = "repealed" if _ROOT_REPEALED_TITLE_RE.fullmatch(note) else ""
        if "repeal" in note.casefold() and not terminal:
            raise ValueError(
                f"New Hampshire title has an untyped repeal note: {number}: {note!r}"
            )
        units.append(
            {
                "title_number": number,
                "title_name": _clean(label_match.group("name")),
                "label": label,
                "source_url": source_url,
                "catalog_note": note,
                "terminal_disposition": terminal,
            }
        )
    return units


def nhtoc_chapter_units(
    html: str,
    *,
    title_number: str,
    base_url: str,
) -> List[Dict[str, str]]:
    """Return one title page's exact chapter frontier."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    title = str(title_number or "").strip().upper()
    if not title:
        raise ValueError("New Hampshire chapter frontier requires a title identity")
    expected_prefix = f"NHTOC-{title}-"
    soup = BeautifulSoup(html or "", "html.parser")
    units: List[Dict[str, str]] = []
    seen_numbers: set[str] = set()
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().replace("\\", "/")
        basename = href.rsplit("/", 1)[-1]
        if not (
            basename.upper().startswith(expected_prefix.upper())
            and basename.lower().endswith(".htm")
        ):
            continue
        chapter = basename[len(expected_prefix) : -4].strip().upper()
        label = _clean(anchor.get_text(" "))
        label_match = _CHAPTER_LABEL_RE.fullmatch(label)
        if (
            not chapter
            or label_match is None
            or label_match.group("number").upper() != chapter
        ):
            raise ValueError(
                f"New Hampshire chapter label does not match its locator: {href!r}"
            )
        source_url = _canonical_source_url(base_url, href)
        key = source_url.casefold()
        if chapter.casefold() in seen_numbers or key in seen_urls:
            raise ValueError(
                f"New Hampshire title {title} contains duplicate chapter {chapter}"
            )
        seen_numbers.add(chapter.casefold())
        seen_urls.add(key)
        chapter_name = _clean(label_match.group("name"))
        units.append(
            {
                "title_number": title,
                "chapter_number": chapter,
                "chapter_name": chapter_name,
                "label": label,
                "source_url": source_url,
                "terminal_disposition": terminal_disposition_from_label(chapter_name)
                or "",
            }
        )
    return units


def nhtoc_section_units(
    html: str,
    *,
    title_number: str,
    chapter_number: str,
    base_url: str,
) -> List[Dict[str, str]]:
    """Return one chapter page's exact section-locator frontier."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    title = str(title_number or "").strip().upper()
    chapter = str(chapter_number or "").strip().upper()
    if not title or not chapter:
        raise ValueError("New Hampshire section frontier requires title and chapter identities")
    soup = BeautifulSoup(html or "", "html.parser")
    units: List[Dict[str, str]] = []
    seen_numbers: set[str] = set()
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().replace("\\", "/")
        if not href.lower().endswith(".htm") or re.search(
            r"-mrg\.htm$", href, re.IGNORECASE
        ):
            continue
        source_url = _canonical_source_url(base_url, href)
        path_parts = [part for part in urlparse(source_url).path.split("/") if part]
        if len(path_parts) < 4:
            continue
        if (
            path_parts[-3].casefold() != title.casefold()
            or path_parts[-2].casefold() != chapter.casefold()
        ):
            continue
        citation = section_citation_from_url(source_url)
        if not citation:
            raise ValueError(
                f"New Hampshire section locator is not derivable: {source_url!r}"
            )
        label = _clean(anchor.get_text(" "))
        label_match = _SECTION_LABEL_RE.fullmatch(label)
        if (
            label_match is None
            or label_match.group("number").casefold() != citation.casefold()
        ):
            raise ValueError(
                f"New Hampshire section label does not match its locator: {source_url!r}"
            )
        key = source_url.casefold()
        citation_key = citation.casefold()
        if citation_key in seen_numbers or key in seen_urls:
            raise ValueError(
                f"New Hampshire chapter {chapter} contains duplicate section {citation}"
            )
        seen_numbers.add(citation_key)
        seen_urls.add(key)
        section_name = _clean(label_match.group("name") or "")
        units.append(
            {
                "title_number": title,
                "chapter_number": chapter,
                "section_number": citation,
                "section_name": section_name,
                "label": label,
                "source_url": source_url,
                "terminal_disposition": terminal_disposition_from_label(section_name)
                or "",
            }
        )
    return units


def nhtoc_title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Title TOC URLs from the master ``NHTOC.htm`` listing."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        roman = match.group(1).upper()
        if roman in seen:
            continue
        seen.add(roman)
        out.append((urljoin(base_url.rstrip("/") + "/", href), roman))
    return out


def nhtoc_chapter_links(html: str) -> List[str]:
    """Chapter TOC filenames from a title ``NHTOC-{ROMAN}.htm`` page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if "/" in href:
            continue
        if not _CHAPTER_HREF_RE.match(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def nhtoc_section_links(html: str) -> List[str]:
    """Relative section hrefs from a chapter TOC (``../TITLE/CH/CH-SEC.htm``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href.startswith("../") or not href.lower().endswith(".htm"):
            continue
        if re.search(r"-mrg\.htm$", href, re.IGNORECASE):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def new_hampshire_section_page_identity(html: str) -> str:
    """Return the exact section citation when the official page agrees with itself."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.find("codesect") is None:
        return ""
    candidates: List[str] = []
    meta = soup.find("meta", attrs={"name": re.compile(r"^sectiontitle$", re.I)})
    if meta is not None:
        match = _SECTION_LABEL_RE.match(_clean(str(meta.get("content") or "")))
        if match:
            candidates.append(match.group("number"))
    heading = soup.find("h3")
    if heading is not None:
        match = _SECTION_LABEL_RE.match(_clean(heading.get_text(" ")))
        if match:
            candidates.append(match.group("number"))
    bold = soup.find("b")
    if bold is not None:
        bold_text = re.sub(r"\s*[\-–—―]+\s*$", "", _clean(bold.get_text(" ")))
        match = re.match(
            r"^(?P<number>[0-9]+(?:-[A-Z0-9]+)*:[0-9A-Z][0-9A-Z.\-]*)\b",
            bold_text,
            flags=re.IGNORECASE,
        )
        if match:
            candidates.append(match.group("number"))
    if not candidates:
        return ""
    identity = candidates[0]
    if any(candidate.casefold() != identity.casefold() for candidate in candidates[1:]):
        return ""
    return identity


def source_bound_terminal_disposition_from_section_html(
    html: str,
    *,
    source_url: str,
    section_number: str,
) -> Optional[Dict[str, str]]:
    """Classify one exact nonoperative RSA section from its own official body."""

    expected = str(section_number or "").strip()
    page_identity = new_hampshire_section_page_identity(html)
    url_identity = section_citation_from_url(source_url)
    if (
        not expected
        or not page_identity
        or page_identity.casefold() != expected.casefold()
        or not url_identity
        or url_identity.casefold() != expected.casefold()
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    codesect = soup.find("codesect")
    body_text = _clean(codesect.get_text(" ") if codesect is not None else "")
    bold = soup.find("b")
    heading_text = _clean(bold.get_text(" ") if bold is not None else "")
    heading_tail = re.sub(
        rf"^{re.escape(expected)}\s*",
        "",
        heading_text,
        flags=re.IGNORECASE,
    ).lstrip(" .:–—-")
    disposition = terminal_disposition_from_label(body_text)
    if disposition is None:
        disposition = terminal_disposition_from_label(heading_tail)
    if disposition is None:
        return None
    return {
        "section_number": expected,
        "source_url": source_url,
        "disposition": disposition,
    }


def parse_new_hampshire_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "New Hampshire RSA",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    codesect = body.find("codesect")
    if codesect is None:
        return None
    full = _clean(codesect.get_text(" "))
    if not full:
        return None
    bold = body.find("b")
    heading = _clean(bold.get_text(" ")) if bold else ""
    heading = re.sub(r"\s*[\-–—―]+\s*$", "", heading).strip()
    page_identity = new_hampshire_section_page_identity(html)
    url_identity = section_citation_from_url(source_url)
    if page_identity and url_identity and page_identity.casefold() != url_identity.casefold():
        return None
    citation = page_identity or url_identity
    if not citation:
        return None
    heading_tail = re.sub(
        rf"^{re.escape(citation)}\s*",
        "",
        heading,
        flags=re.IGNORECASE,
    ).lstrip(" .:–—-")
    if terminal_disposition_from_label(full) or terminal_disposition_from_label(
        heading_tail
    ):
        return None
    name = heading or f"Section {citation}"
    return NormalizedStatute(
        state_code="NH",
        state_name="New Hampshire",
        statute_id=f"{code_name} § {citation}",
        code_name=code_name,
        chapter_number=citation.split(":", 1)[0] if ":" in citation else None,
        section_number=citation,
        section_name=name[:200],
        full_text=full,
        source_url=source_url or BASE,
        official_cite=f"N.H. Rev. Stat. § {citation}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_new_hampshire_rsa_html",
            "source_authority_class": "official",
            "discovery_method": "gencourt_codesect",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_CHAPTER_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_chapter_toc_html() -> List[str]:
    path = configured_chapter_toc_html_path()
    if path is None:
        return []
    return nhtoc_section_links(path.read_text(encoding="utf-8", errors="replace"))


def configured_section_html_paths() -> List[Path]:
    paths: List[Path] = []
    single = configured_section_html_path()
    if single is not None:
        paths.append(single)
    raw_dir = str(os.environ.get("NEW_HAMPSHIRE_SECTION_HTML_DIR") or "").strip()
    if raw_dir:
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".htm", ".html"}
                )
            )
    return paths


def section_url_from_path(path: Path) -> str:
    stem = path.stem
    chapter = stem.split("-")[0] if "-" in stem else stem
    return f"{BASE}/{chapter}/{path.name}"


def parse_configured_new_hampshire_sections(
    *,
    code_name: str = "New Hampshire RSA",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    wanted: Optional[set[str]] = None
    toc_path = configured_chapter_toc_html_path()
    if toc_path is not None:
        wanted = {
            Path(href).name.lower()
            for href in nhtoc_section_links(
                toc_path.read_text(encoding="utf-8", errors="replace")
            )
        }
    for path in configured_section_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if wanted is not None and path.name.lower() not in wanted:
            continue
        row = parse_new_hampshire_section_html(
            path.read_text(encoding="utf-8", errors="replace"),
            source_url=section_url_from_path(path),
            code_name=code_name,
        )
        if row is None:
            continue
        key = str(row.section_number or "")
        if key in seen:
            continue
        seen.add(key)
        statutes.append(row)
    return statutes
