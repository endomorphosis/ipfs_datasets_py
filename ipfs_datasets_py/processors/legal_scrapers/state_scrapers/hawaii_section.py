"""Official Hawaii HRS section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeHI.py`` (Apache-2.0).
First ``<p>`` carries ``§ N-N. heading`` plus body; later paragraphs stop
at notes headings or ``[L 1892`` history.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.capitol.hawaii.gov"
_NOTES_HEADINGS = {
    "attorney general opinions",
    "law journals and reviews",
    "case notes",
    "rules of court",
    "cross references",
    "revision notes",
    "compiler's notes",
    "note",
    "notes",
    "history",
    "history of section",
    "editor's note",
    "source",
    "annotations",
}
_HISTORY_RE = re.compile(r"\[?[Ll]\s+\d{4}")
_RESERVED = re.compile(r"\(repealed\)|\(expired\)|\(reserved\)|--repealed", re.IGNORECASE)
_SEC_RE = re.compile(r"§\s*([\d][\w.\-:]*)")
_FILE_RE = re.compile(
    r"HRS_(\d{4}[A-Z]?)-([^/?#]+)\.HTM$",
    re.IGNORECASE,
)
_SECTION_HEADING_RE = re.compile(r"^\s*\[?\s*§\s*([\d][\w.\-:]*)")
_WS = re.compile(r"\s+")
_NEXT_TEXT_RE = re.compile(r"^\s*next\s*(?:>+|»|&gt;)?\s*$", re.IGNORECASE)
_CHAPTER_PREFIX_RE = re.compile(r"^(.*/HRS\d+[A-Z]*/)", re.IGNORECASE)
_OFFICIAL_CHAPTER_PATH_RE = re.compile(
    r"^/hrscurrent/(?P<volume>Vol[^/]+)/HRS(?P<chapter>\d{4}[A-Z]?)/$",
    re.IGNORECASE,
)
_OFFICIAL_CHAPTER_SENTINEL_PATH_RE = re.compile(
    r"^/hrscurrent/(?P<volume>Vol[^/]+)/HRS(?P<chapter>\d{4}[A-Z]?)/"
    r"HRS_(?P=chapter)-\.htm$",
    re.IGNORECASE,
)
_OFFICIAL_SECTION_PATH_RE = re.compile(
    r"^/hrscurrent/(?P<volume>Vol[^/]+)/HRS(?P<chapter>\d{4}[A-Z]?)/"
    r"HRS_(?P=chapter)-[^/]+\.htm$",
    re.IGNORECASE,
)

# Exact current-HRS operative inventory.  The digest covers the canonical JSON
# list of ``source_url``/``statute_id`` pairs, sorted by those two fields.  It
# is intentionally separate from the 373 typed nonoperative locators owned by
# ``HawaiiScraper``.
HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT = 22_600
HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT = 22_973
HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256 = (
    "493351e0c442c5918e149af2cd16f5e1799267eb140605b8f62912bae5e61abe"
)
_HRS_SCAFFOLD_TEXT_RE = re.compile(
    r"^\s*Section\s+Section-\d+\s*:",
    re.IGNORECASE,
)
_OFFICIAL_HAWAII_HOSTS = {
    "data.capitol.hawaii.gov",
    "www.capitol.hawaii.gov",
}
_SOURCE_BOUND_NONOPERATIVE_CHAPTER_SENTINELS = {
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol02_Ch0046-0115/"
        "HRS0070/HRS_0070-.htm"
    ): {
        "content_sha256": (
            "b6baa7aacaca490f97be2b9f90de9e8f05dc8c373a4af36e562b68c615276d5d"
        ),
        "terminal_paragraphs": ("REPEALED. L 1988, c 263, §11.",),
    },
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol02_Ch0046-0115/"
        "HRS0085/HRS_0085-.htm"
    ): {
        "content_sha256": (
            "847c2670c053e345dc767b4aa2f4a7a07b8a05de5898d78b231f2d706b109597"
        ),
        "terminal_paragraphs": (
            "§§85-1 to 25 REPEALED. L 1972, c 26, §1.",
            "§§85-31 to 48 REPEALED. L 1993, c 63, §1.",
        ),
    },
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol12_Ch0501-0588/"
        "HRS0573/HRS_0573-.htm"
    ): {
        "content_sha256": (
            "6b2d31ee5673ff735567dc6305c11db99248fe71f766c4ed715dff6383cdc04c"
        ),
        "terminal_paragraphs": ("REPEALED. L 1987, c 46, §4.",),
    },
}
_SOURCE_BOUND_RESERVED_ARTICLE_URL = (
    "https://data.capitol.hawaii.gov/hrscurrent/Vol09_Ch0431-0435H/"
    "HRS0431/HRS_0431-0018-0101.htm"
)
_SOURCE_BOUND_RESERVED_ARTICLE_SHA256 = (
    "47d0f3190832cc2c63f5d94169c515422c0a1d74d7c90eaf9ff2535ebab9be56"
)
_SOURCE_BOUND_SECTION_CITATION_MISMATCHES = {
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol02_Ch0046-0115/"
        "HRS0092/HRS_0092-0007_0005.htm"
    ): {
        "content_sha256": (
            "7f19496a4a1eeeb5a368c548029419d606ed9c38d32443bab830f12eb2a2cf18"
        ),
        "printed_section": "9",
    },
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol12_Ch0501-0588/"
        "HRS0514B/HRS_0514B-0103.htm"
    ): {
        "content_sha256": (
            "bdd3ef58ebecb45161b787f7b7f5313913f469a25d83674e9030c6eae0e19151"
        ),
        "printed_section": "514B-10",
    },
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol13_Ch0601-0676/"
        "HRS0634G/HRS_0634G-0002.htm"
    ): {
        "content_sha256": (
            "98fe1bac22900a676e4ed76daad7f49d56c07e3b9bb93258616d13d81b4576f4"
        ),
        "printed_section": "643G-2",
    },
}
_SOURCE_BOUND_NONOPERATIVE_SECTION_DISPOSITIONS = {
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
        "HRS0011/HRS_0011-0191.htm"
    ): {
        "content_sha256": (
            "ef3d5e7e575e87fb42f98952f19084d2deed7b0ddf48f1a7a2c7040b1b75b410"
        ),
        "disposition": "repealed",
        "paragraphs": (
            "B. Election Campaign Contributions",
            "and Expenditures--Repealed",
            "§§11-191 to 11-213 [OLD] REPEALED. L 1979, c 224.",
            "§ §11-191 to 11-225 REPEALED. L 2010, c 211, §9.",
        ),
    },
    (
        "https://data.capitol.hawaii.gov/hrscurrent/Vol08_Ch0401-0429/"
        "HRS0425/HRS_0425-0180.htm"
    ): {
        "content_sha256": (
            "fd842546d6749d0e45073da77cbed40710726a0bcd327c818fe410342ef2c298"
        ),
        "disposition": "repealed",
        "paragraphs": (
            "PART V. LIMITED LIABILITY PARTNERSHIP ACT--REPEALED",
            "§§425-151 to 425-180 REPEALED. L 2000, c 218, §8.",
            "Note",
            "L 2000, c 219, §§56 to 59 purports to amend §§425-164, "
            + "425-169, 425-171, and 425-172.",
        ),
    },
}
_SECTION_CITATION_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€")


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    return _WS.sub(" ", _fix_encoding((text or "").replace("\xa0", " "))).strip()


def _normalize_section_citation_text(text: str) -> str:
    """Normalize only publisher typography that can split an HRS citation."""

    value = _clean(text).translate(_SECTION_CITATION_DASH_TRANSLATION)
    value = re.sub(r"(?<=\w)\s*([:-])\s*(?=\w)", r"\1", value)
    value = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", value)
    # Current Word exports split a three-or-more-character chapter token
    # after its first digit (for example ``§2 06E-241`` and ``§4 31:3``).
    # Requiring at least two following digits deliberately leaves the shorter
    # retained ``§9 2-7.5`` anomaly to its URL+digest binding below.
    return re.sub(r"(?<=§)(\d)\s+(?=\d{2,}[A-Z]?\s*[:-])", r"\1", value)


def _heading_section_number(text: str) -> str:
    match = _SECTION_HEADING_RE.match(_normalize_section_citation_text(text))
    return match.group(1).rstrip(".") if match else ""


def chapter_prefix(chapter_url: str) -> Optional[str]:
    match = _CHAPTER_PREFIX_RE.match(str(chapter_url or ""))
    return match.group(1) if match else None


def find_next_link(html: str, *, current_url: str) -> Optional[str]:
    """Absolute URL of the chapter/section ``Next`` link, if present."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        if not _NEXT_TEXT_RE.match(_clean(anchor.get_text(" "))):
            continue
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        return urljoin(current_url, href)
    return None


def nonoperative_chapter_marker_url(
    html: str,
    *,
    chapter_url: str,
) -> Optional[str]:
    """Return an exact official chapter tombstone link from an autoindex.

    Hawaii's static publisher leaves repealed or reserved chapters in the
    official volume hierarchy as a two-link IIS autoindex: one parent link and
    one same-chapter ``HRS_<chapter>-.htm`` marker.  An empty directory, an
    approximate filename, or an autoindex with any additional link is not
    terminal evidence.
    """

    parsed = urlsplit(str(chapter_url or ""))
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in _OFFICIAL_HAWAII_HOSTS
        or parsed.query
        or parsed.fragment
    ):
        return None
    path = parsed.path if parsed.path.endswith("/") else f"{parsed.path}/"
    match = _OFFICIAL_CHAPTER_PATH_RE.fullmatch(path)
    if match is None:
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    expected_identity = f"{hostname} - {path}"
    title = _clean(soup.title.get_text(" ") if soup.title else "")
    heading = _clean(soup.h1.get_text(" ") if soup.h1 else "")
    if title != expected_identity or heading != expected_identity:
        return None

    canonical_chapter_url = parsed._replace(path=path).geturl()
    parent_url = urljoin(canonical_chapter_url, "../")
    chapter = match.group("chapter").upper()
    filename = f"HRS_{chapter}-.htm"
    marker_url = urljoin(canonical_chapter_url, filename)
    anchors = [
        (
            _clean(anchor.get_text(" ")),
            urljoin(canonical_chapter_url, str(anchor.get("href") or "").strip()),
        )
        for anchor in soup.find_all("a", href=True)
    ]
    if anchors != [
        ("[To Parent Directory]", parent_url),
        (filename, marker_url),
    ]:
        return None
    return marker_url


def nonoperative_hawaii_chapter_disposition(
    html: str,
    *,
    sentinel_url: str,
) -> Optional[str]:
    """Classify an exact official same-chapter tombstone body."""

    parsed = urlsplit(str(sentinel_url or ""))
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in _OFFICIAL_HAWAII_HOSTS
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = _OFFICIAL_CHAPTER_SENTINEL_PATH_RE.fullmatch(parsed.path)
    if match is None:
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")

    anchors = [
        (
            _clean(anchor.get_text(" ")),
            urljoin(str(sentinel_url), str(anchor.get("href") or "").strip()),
        )
        for anchor in soup.find_all("a", href=True)
    ]
    if len(anchors) != 3 or [label.lower() for label, _url in anchors] != [
        "previous",
        match.group("volume").lower(),
        "next",
    ]:
        return None
    volume_url = urljoin(str(sentinel_url), "../")
    if anchors[1][1].rstrip("/") != volume_url.rstrip("/"):
        return None
    for _label, linked_url in (anchors[0], anchors[2]):
        linked = urlsplit(linked_url)
        if (
            (linked.hostname or "").lower() != hostname
            or not linked.path.lower().startswith("/hrscurrent/")
            or not linked.path.lower().endswith(".htm")
        ):
            return None

    text = _clean(soup.get_text(" "))
    paragraphs = [
        value
        for value in (_clean(node.get_text(" ")) for node in soup.find_all("p"))
        if value
    ]
    chapter = match.group("chapter").upper()
    printed_chapter = chapter.lstrip("0") or "0"
    source_bound = _SOURCE_BOUND_NONOPERATIVE_CHAPTER_SENTINELS.get(
        str(sentinel_url)
    )
    if source_bound is not None:
        digest = hashlib.sha256(str(html or "").encode("utf-8")).hexdigest()
        required = tuple(source_bound.get("terminal_paragraphs") or ())
        if (
            digest == str(source_bound.get("content_sha256") or "")
            and re.search(
                rf"\bCHAPTER\s+{re.escape(printed_chapter)}\b",
                text,
                re.IGNORECASE,
            )
            and required
            and all(paragraph in paragraphs for paragraph in required)
        ):
            return "repealed"
        return None

    # Ordinary chapter sentinels cannot hide an operative section paragraph.
    # The three byte-bound notices above are the only current pages whose
    # post-terminal revision notes themselves begin with a section glyph.
    if any(re.match(r"^\s*§", paragraph) for paragraph in paragraphs):
        return None
    if re.search(
        rf"\bCHAPTER\s+{re.escape(printed_chapter)}\b.*?\bREPEALED\s*\.",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        return "repealed"

    reserved = re.search(
        r"\[\s*CHAPTERS?\s+(\d+[A-Z]?)"
        r"(?:\s+TO\s+(\d+[A-Z]?))?\s+RESERVED\s*\.\s*\]",
        text,
        re.IGNORECASE,
    )
    if reserved and reserved.group(1).upper() == printed_chapter:
        return "reserved"
    return None


def _strip_heading(text: str) -> str:
    text = _normalize_section_citation_text(text)
    match = re.match(
        r"^\s*\[?§\s*[\d][\w.\-:]*\s*\]?\s+[^.]{1,200}\.\s+(.*)",
        text,
        re.DOTALL,
    )
    return match.group(1).strip() if match else text


def _unpadded_component(value: str) -> str:
    match = re.fullmatch(r"0*(\d+)([A-Z]?)", str(value or ""), re.IGNORECASE)
    if not match:
        return str(value or "").strip()
    return f"{int(match.group(1))}{match.group(2).upper()}"


def section_number_from_url(source_url: str) -> str:
    """Decode all official HRS filename forms into their printed citation.

    Most files use ``HRS_0010-0014_0005.htm`` (10-14.5).  The banking and
    insurance codes use an article separator, for example
    ``HRS_0412-0001-0100.htm`` (412:1-100).  A few official links contain a
    stray soft hyphen; it is presentation noise rather than part of the cite.
    """

    raw_path = unquote(urlsplit(str(source_url or "")).path).replace("\xad", "")
    match = _FILE_RE.search(raw_path)
    if not match:
        return ""
    chapter = _unpadded_component(match.group(1))
    raw_tail = match.group(2).replace("\xad", "")
    raw_tail = re.sub(r"_\[OLD\]$", "", raw_tail, flags=re.IGNORECASE)
    raw_tail = re.sub(r"\.docx$", "", raw_tail, flags=re.IGNORECASE)
    tail_groups = raw_tail.split("-")

    def _normalize_group(group: str) -> str:
        components = [
            _unpadded_component(component)
            for component in group.split("_")
            if component
        ]
        if not components:
            return ""
        if len(components) == 1:
            return components[0]
        # The static publisher splits each decimal run into padded filename
        # components: ``0014_0005_0005`` is printed as 14.55, not 14.5.5.
        return f"{components[0]}.{''.join(components[1:])}"

    normalized_groups = [_normalize_group(group) for group in tail_groups]
    if not chapter or not normalized_groups or any(not group for group in normalized_groups):
        return ""
    if len(normalized_groups) > 1:
        return f"{chapter}:{normalized_groups[0]}-{'-'.join(normalized_groups[1:])}"
    return f"{chapter}-{normalized_groups[0]}"


def _flexible_citation_pattern(number: str) -> str:
    """Return an exact citation pattern that tolerates publisher whitespace."""

    return r"\s*".join(re.escape(character) for character in str(number or ""))


def _has_exact_official_section_navigation(
    soup: object,
    *,
    source_url: str,
    volume: str,
) -> bool:
    page_links = soup.select_one("div#pageLinks")  # type: ignore[attr-defined]
    if page_links is None:
        return False
    anchors = [
        (
            _clean(anchor.get_text(" ")),
            urljoin(str(source_url), str(anchor.get("href") or "").strip()),
        )
        for anchor in page_links.find_all("a", href=True)
    ]
    if len(anchors) != 3 or [label.lower() for label, _url in anchors] != [
        "previous",
        volume.lower(),
        "next",
    ]:
        return False

    parsed_source = urlsplit(source_url)
    expected_volume_path = f"/hrscurrent/{volume}"
    middle = urlsplit(anchors[1][1])
    if (
        middle.scheme.lower() != "https"
        or (middle.hostname or "").lower() != (parsed_source.hostname or "").lower()
        or middle.path.rstrip("/") != expected_volume_path
        or middle.query
        or middle.fragment
    ):
        return False
    section_prefix = f"{expected_volume_path}/HRS"
    for _label, linked_url in (anchors[0], anchors[2]):
        linked = urlsplit(linked_url)
        if (
            linked.scheme.lower() != "https"
            or (linked.hostname or "").lower()
            != (parsed_source.hostname or "").lower()
            or not linked.path.startswith(section_prefix)
            or not linked.path.lower().endswith(".htm")
            or linked.query
            or linked.fragment
        ):
            return False
    return True


def nonoperative_hawaii_section_disposition(
    html: str,
    *,
    source_url: str,
) -> Optional[str]:
    """Classify an exact official grouped section disposition locator.

    A disposition closes one locator only when the official filename identity,
    Word-export body, three-link navigation, and the first locus in the printed
    disposition agree.  It never treats a generic short or heading-less page as
    nonoperative.  Two current ambiguous pages are additionally byte-bound.
    """

    parsed_url = urlsplit(str(source_url or ""))
    hostname = (parsed_url.hostname or "").lower()
    path_match = _OFFICIAL_SECTION_PATH_RE.fullmatch(parsed_url.path)
    if (
        parsed_url.scheme.lower() != "https"
        or hostname not in _OFFICIAL_HAWAII_HOSTS
        or parsed_url.query
        or parsed_url.fragment
        or path_match is None
    ):
        return None
    expected = section_number_from_url(source_url)
    if not expected:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    article = soup.select_one("div.WordSection1")
    if article is None or not _has_exact_official_section_navigation(
        soup,
        source_url=source_url,
        volume=path_match.group("volume"),
    ):
        return None
    paragraphs = [
        text
        for text in (_clean(node.get_text(" ")) for node in article.find_all("p"))
        if text
    ]
    if not paragraphs:
        return None

    source_bound = _SOURCE_BOUND_NONOPERATIVE_SECTION_DISPOSITIONS.get(
        str(source_url)
    )
    if source_bound is not None:
        digest = hashlib.sha256(str(html or "").encode("utf-8")).hexdigest()
        if (
            digest == str(source_bound.get("content_sha256") or "")
            and tuple(paragraphs) == tuple(source_bound.get("paragraphs") or ())
        ):
            return str(source_bound.get("disposition") or "") or None
        return None

    expected_pattern = _flexible_citation_pattern(expected)
    group_prefix = re.compile(
        rf"^\s*§\s*§\s*{expected_pattern}(?![\w.:-])",
        re.IGNORECASE,
    )
    dispositions: list[str] = []
    for paragraph in paragraphs:
        normalized = _normalize_section_citation_text(paragraph)
        match = group_prefix.match(normalized)
        if match is None:
            continue
        remainder = normalized[match.end() :]
        if re.search(r"\bREPEALED\s*\.", remainder, re.IGNORECASE):
            dispositions.append("repealed")
        elif re.search(r"\bRESERVED\s*\.\s*$", remainder, re.IGNORECASE):
            dispositions.append("reserved")
        elif re.search(
            r"\bRENUMBERED\s+AS\s+§\s*§?\s*[\d]",
            remainder,
            re.IGNORECASE,
        ):
            dispositions.append("renumbered")
    # The one current singular slot is a complete one-paragraph parenthetical
    # reservation.  A singular operative heading cannot be hidden by this path.
    singular_reserved = re.compile(
        rf"^\s*\[?\s*§\s*{expected_pattern}\s*\]?\s*"
        r"\(RESERVED\)\s*$",
        re.IGNORECASE,
    )
    for paragraph in paragraphs:
        normalized = _normalize_section_citation_text(paragraph)
        if singular_reserved.fullmatch(normalized):
            if len(paragraphs) == 1 and not dispositions:
                return "reserved"
            return None
        printed = _heading_section_number(normalized)
        if printed and not re.search(
            r"\b(?:REPEALED|RESERVED|RENUMBERED)\b",
            normalized,
            re.IGNORECASE,
        ):
            return None
        if re.match(r"^\s*Rule\s+\d", normalized, re.IGNORECASE):
            return None
    if len(dispositions) != 1:
        # The exact two-marker 11-191 body is admitted only by its digest-bound
        # branch above; all unbound extra disposition rows remain drift.
        return None
    return dispositions[0]


def is_nonoperative_hawaii_section_html(
    html: str,
    *,
    source_url: str = "",
) -> bool:
    """Whether a section page is an exact nonoperative official slot."""

    if source_url:
        return (
            nonoperative_hawaii_section_disposition(
                html,
                source_url=source_url,
            )
            is not None
        )

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return False
    soup = BeautifulSoup(html or "", "html.parser")
    for paragraph in soup.find_all("p"):
        text = _clean(paragraph.get_text(" "))
        if not text:
            continue
        if _SEC_RE.search(text) or _RESERVED.search(text):
            return bool(_RESERVED.search(text))
    return False


def is_source_bound_nonoperative_hawaii_section_html(
    html: str,
    *,
    source_url: str,
) -> bool:
    """Recognize the one digest-bound reserved article without a ``§`` row.

    The official ``431:18-101`` locator is a navigation slot whose complete
    statutory body is ``ARTICLE 18 [RESERVED]``.  It deliberately falls
    outside the generic nonoperative classifier: admission requires the exact
    official URL, retained byte digest, article structure, and navigation
    neighbors observed in the 2026 HRS hierarchy.
    """

    if str(source_url or "") != _SOURCE_BOUND_RESERVED_ARTICLE_URL:
        return False
    payload = str(html or "").encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != _SOURCE_BOUND_RESERVED_ARTICLE_SHA256:
        return False
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return False
    soup = BeautifulSoup(html or "", "html.parser")
    if _clean(soup.title.get_text(" ") if soup.title else "") != "ARTICLE 18":
        return False
    article = soup.select_one("div.WordSection1")
    if article is None:
        return False
    paragraphs = [
        text
        for text in (_clean(node.get_text(" ")) for node in article.find_all("p"))
        if text
    ]
    if paragraphs != ["ARTICLE 18", "[RESERVED]"]:
        return False
    page_links = soup.select_one("div#pageLinks")
    if page_links is None:
        return False
    anchors = [
        (
            _clean(anchor.get_text(" ")),
            urljoin(str(source_url), str(anchor.get("href") or "").strip()),
        )
        for anchor in page_links.find_all("a", href=True)
    ]
    return anchors == [
        (
            "Previous",
            "https://data.capitol.hawaii.gov/hrscurrent/Vol09_Ch0431-0435H/"
            + "HRS0431/HRS_0431-0017-0101.htm",
        ),
        (
            "Vol09_Ch0431-0435H",
            "https://data.capitol.hawaii.gov/hrscurrent/Vol09_Ch0431-0435H",
        ),
        (
            "Next",
            "https://data.capitol.hawaii.gov/hrscurrent/Vol09_Ch0431-0435H/"
            + "HRS0431/HRS_0431-0019-0101.htm",
        ),
    ]


def parse_hawaii_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Hawaii Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    paragraphs = soup.find_all("p")
    if not paragraphs:
        return None
    number = section_number_from_url(source_url)
    first_index = -1
    first = ""
    first_is_hre_rule = False
    first_heading_index = -1
    first_heading = ""
    for index, paragraph in enumerate(paragraphs):
        candidate = _clean(paragraph.get_text(" "))
        normalized_candidate = _normalize_section_citation_text(candidate)
        if number.startswith("626:1-"):
            expected_rule = number.removeprefix("626:1-")
            rule_match = re.match(
                r"^\s*Rule\s+([\d]+(?:\.[\d]+)?)(?![\d.])(?:\s|$)",
                normalized_candidate,
                re.IGNORECASE,
            )
            if rule_match and rule_match.group(1) == expected_rule:
                first_index = index
                first = normalized_candidate
                first_is_hre_rule = True
                break
        printed_number = _heading_section_number(candidate)
        if not printed_number:
            continue
        if first_heading_index < 0:
            first_heading_index = index
            first_heading = candidate
        if not number or printed_number == number:
            first_index = index
            first = candidate
            break
    if first_index < 0 and number and first_heading_index >= 0:
        source_bound = _SOURCE_BOUND_SECTION_CITATION_MISMATCHES.get(
            str(source_url or "")
        )
        digest = hashlib.sha256(str(html or "").encode("utf-8")).hexdigest()
        if (
            source_bound is not None
            and digest == str(source_bound.get("content_sha256") or "")
            and _heading_section_number(first_heading)
            == str(source_bound.get("printed_section") or "")
        ):
            first_index = first_heading_index
            first = first_heading
    if first_index < 0:
        return None
    if _RESERVED.search(first):
        return None
    normalized_first = _normalize_section_citation_text(first)
    if not number:
        number = _heading_section_number(normalized_first)
    if not number:
        return None
    if first_is_hre_rule:
        name_match = re.match(
            r"^\s*Rule\s+[\d]+(?:\.[\d]+)?\s+([^.]{1,150})\.",
            normalized_first,
            re.IGNORECASE,
        )
    else:
        name_match = re.match(
            r"^\s*\[?§\s*[\d][\w.\-:]*\s*\]?\s+([^.]{1,150})\.",
            normalized_first,
        )
    name = name_match.group(1).strip() if name_match else f"Section {number}"
    history_boundary = r"\s+(?=\[(?:Am\s+)?L\s+\d{4})"
    hist_split = re.split(history_boundary, first, maxsplit=1)
    if first_is_hre_rule:
        stripped = re.sub(
            r"^\s*Rule\s+[\d]+(?:\.[\d]+)?\s+[^.]{1,200}\.\s*",
            "",
            hist_split[0],
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
    else:
        stripped = _strip_heading(hist_split[0])
    body_parts = [stripped]
    if len(hist_split) > 1:
        paragraphs = paragraphs[: first_index + 1]
    for para in paragraphs[first_index + 1 :]:
        text = _clean(para.get_text(" "))
        if not text:
            continue
        lower = text.lower().rstrip(":").rstrip(".")
        if lower in _NOTES_HEADINGS or any(lower.startswith(head) for head in _NOTES_HEADINGS):
            break
        if _HISTORY_RE.match(text) or text.startswith("[L ") or text.startswith("[Am"):
            break
        history_split = re.split(history_boundary, text, maxsplit=1)
        if history_split[0]:
            body_parts.append(history_split[0])
        if len(history_split) > 1:
            break
    body = _clean(" ".join(part for part in body_parts if part))
    if not body:
        return None
    return NormalizedStatute(
        state_code="HI",
        state_name="Hawaii",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=number.split("-", 1)[0],
        section_number=number,
        section_name=name[:200],
        full_text=body,
        source_url=source_url or f"{BASE}/docs/hrs.htm",
        official_cite=f"Haw. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_hawaii_hrs_html",
            "source_authority_class": "official",
            "discovery_method": "capitol_hrs_section_p",
            "skip_hydrate": True,
        },
    )


def is_source_bound_operative_hawaii_statute(statute: object) -> bool:
    """Recognize only a row proven by the exact closed official HRS walk.

    This is the narrow admission seam used by both generic quality gates.  It
    does not trust an ``official`` label by itself: URL/filename identity,
    parser kind, closed-frontier cardinality, and the sealed operative
    identity digest must all agree.  Placeholder scaffold text remains
    ineligible even when those metadata fields are forged.
    """

    def value(name: str, default: Any = "") -> Any:
        if isinstance(statute, Mapping):
            return statute.get(name, default)
        return getattr(statute, name, default)

    structured = value("structured_data", {})
    if not isinstance(structured, Mapping):
        return False
    source_url = str(value("source_url") or "").strip()
    try:
        parsed_url = urlsplit(source_url)
        host = str(parsed_url.hostname or "").lower().strip(".")
        port = parsed_url.port
    except (TypeError, ValueError):
        return False
    if (
        parsed_url.scheme.lower() != "https"
        or host not in _OFFICIAL_HAWAII_HOSTS
        or port is not None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or _OFFICIAL_SECTION_PATH_RE.fullmatch(parsed_url.path) is None
    ):
        return False

    section_number = str(value("section_number") or "").strip()
    code_name = str(value("code_name") or "").strip()
    full_text = str(value("full_text") or "").strip()
    if (
        not section_number
        or not full_text
        or _HRS_SCAFFOLD_TEXT_RE.match(full_text)
        or section_number_from_url(source_url) != section_number
    ):
        return False

    return bool(
        str(value("state_code") or "").strip().upper() == "HI"
        and str(value("state_name") or "").strip() == "Hawaii"
        and code_name == "Hawaii Revised Statutes"
        and str(value("statute_id") or "").strip()
        == f"{code_name} § {section_number}"
        and str(value("official_cite") or "").strip()
        == f"Haw. Rev. Stat. § {section_number}"
        and str(value("section_name") or "").strip()
        and structured.get("source_kind") == "official_hawaii_hrs_html"
        and structured.get("source_authority_class") == "official"
        and structured.get("discovery_method") == "capitol_hrs_section_p"
        and structured.get("frontier_closed") is True
        and structured.get("frontier_section_locator_count")
        == HAWAII_EXPECTED_TOTAL_SECTION_LOCATOR_COUNT
        and structured.get("frontier_operative_section_count")
        == HAWAII_EXPECTED_OPERATIVE_SECTION_COUNT
        and structured.get("frontier_operative_section_inventory_sha256")
        == HAWAII_EXPECTED_OPERATIVE_SECTION_INVENTORY_SHA256
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("HAWAII_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("HAWAII_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_next_link(*, current_url: str = "") -> Optional[str]:
    path = configured_chapter_html_path()
    if path is None:
        return None
    url = str(current_url or os.environ.get("HAWAII_CHAPTER_URL") or "").strip() or BASE
    return find_next_link(
        path.read_text(encoding="utf-8", errors="replace"),
        current_url=url,
    )
