"""Official Maine MRS section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeME.py`` (Apache-2.0).
Body lives in ``div.MRSSection``; ``heading_section`` is skipped and
``qhistory`` is dropped.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.maine.gov/legis/statutes"
_SEC_RE = re.compile(r"§\s*(?P<num>[\w\-]+)\.\s*(?P<head>.*)$")
_TITLE_RE = re.compile(r"/title(?P<title>[\w\-]+)sec(?P<section>[\w\-]+)\.html$", re.IGNORECASE)
_OFFICIAL_SECTION_PATH_RE = re.compile(
    r"^/(?:legis/)?statutes/(?P<title>[0-9A-Za-z\-]+)/"
    r"title(?P=title)sec(?P<section>[0-9A-Za-z\-]+)\.html$",
    re.IGNORECASE,
)
_OFFICIAL_CHAPTER_PATH_RE = re.compile(
    r"^/statutes/(?P<title>[0-9A-Za-z\-]+)/"
    r"title(?P=title)ch(?P<chapter>[0-9A-Za-z\-]+)sec0\.html$",
    re.IGNORECASE,
)
_DOCUMENT_TITLE_RE = re.compile(
    r"^Title\s+(?P<title>[0-9A-Za-z\-]+),\s*"
    r"§\s*(?P<section>[0-9A-Za-z\-]+):\s*.*$",
    re.IGNORECASE,
)
_VISIBLE_TITLE_RE = re.compile(
    r"^Title\s+(?P<title>[0-9A-Za-z\-]+)(?::|$)",
    re.IGNORECASE,
)
_REALLOCATED_HEADNOTE_RE = re.compile(
    r"^\(REALLOCATED\s+(?P<direction>FROM|TO)\s+TITLE\s+"
    r"[0-9A-Z\-]+,\s+SECTION\s+[0-9A-Z\-]+\)$"
)
_CONTINGENT_REPEAL_HEADNOTE_RE = re.compile(
    r"^\(WHOLE SECTION TEXT REPEALED ON CONTINGENCY:\s+See\s+"
    r"PL\s+\d{4},\s+c\.\s+[0-9A-Z\-]+,\s+§[0-9A-Z\-]+\)$"
)
_CONFLICT_REPEAL_HEADNOTE_RE = re.compile(
    r"^\(WHOLE SECTION CONFLICT:\s+Text as repealed by\s+"
    r"PL\s+\d{4},\s+c\.\s+[0-9A-Z\-]+"
    r"(?:,\s+Pt\.\s+[0-9A-Z\-]+)?,\s+§[0-9A-Z\-]+\)$"
)
_EXACT_SPECIAL_REPEAL_HEADNOTES = frozenset(
    {
        (
            "Persons required to have vision examinations "
            "(REPEALED by PL 1977, c. 620, §1)"
        ),
    }
)
_EXACT_DATED_REPEAL_HEADNOTES = {
    ("22", "1553-a-2"): (
        "(WHOLE SECTION TEXT REPEALED 1/5/26 by PL 2025, c. 367, §§7, 20)",
        "repealed_effective_dated",
    ),
    ("22", "1716-2"): (
        "(WHOLE SECTION TEXT REPEALED 7/01/26 by PL 2025, c. 488, §§2, 8)",
        "repealed_effective_dated",
    ),
    ("36", "4365-f-2"): (
        "(WHOLE SECTION TEXT REPEALED 1/05/26)",
        "repealed_effective_dated",
    ),
}
# These current official pages carry no headnote or statutory body.  Their
# exact official locator, visible section identity, and normalized history
# digest bind the otherwise ambiguous history-only terminal classification.
_EXACT_HISTORY_ONLY_TERMINALS = {
    ("14", "556-2"): (
        "556",
        "e13e5e6e062545dd8d46fe860a78fd0461d3bee1ce34c1cb483bb596e06e63d1",
        "repealed",
    ),
    ("34-a", "4102"): (
        "4102",
        "e63ac68055367f2e0ae67682fe437d1d53a91c55fb1d54dc2810c3d040012cc5",
        "repealed",
    ),
    ("34-a", "5403"): (
        "5403",
        "f8e1ac7e7ff292da42543432616b62bcb4c8bd2bf6d6230aa1eddbbbce351b05",
        "repealed",
    ),
    ("17", "3241"): (
        "3241",
        "4c35de0642e46403435821d4160d04cc2230c1dc424ddf021391639a98116455",
        "repealed",
    ),
}
_EXACT_NOTE_ONLY_TERMINALS = {
    ("29-a", "2354-e"): (
        "2354-E",
        "f7749f139bfa5e00ad09af4d20905524ff72140c8d57f1f1463c2d03423da8a3",
        "never_effective",
    ),
}
_EXACT_NOTE_ONLY_OPERATIVE_SECTIONS = {
    ("10", "1351"): (
        "1351",
        "8bad04665ec429a8b8460d67e39a3f71555559af870f41476352a7ff57428425",
    ),
}
# The current title catalog explicitly types exactly two chapter documents
# whose official chapter pages contain no section links.  Bind those terminals
# to the URL identity, the complete catalog label, and the chapter heading so
# an unrelated empty/scaffold page can never be silently excluded.
_EXACT_EMPTY_CHAPTER_TERMINALS = {
    ("22", "565"): (
        "9e3c0a93c56c2fadadc442da4d416293f6b55fcb3acc9710821862fd07c26fe5",
        "Title 22, Chapter 565: GENETICALLY ENGINEERED PRODUCTS",
        "never_effective_chapter",
    ),
    ("22", "1081"): (
        "2526b72c9868683307cefa06d7fe8855a87e6b8368293b6f92af46e2082d8ef4",
        "Title 22, Chapter 1081: MAINE CHILDREN'S TRUST FUND",
        "repealed_chapter",
    ),
}
_WS = re.compile(r"\s+")
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


def _node_classes(node: object) -> set[str]:
    getter = getattr(node, "get", None)
    if not callable(getter):
        return set()
    return {str(value) for value in (getter("class") or [])}


def _official_section_locator(source_url: str) -> Optional[Tuple[str, str]]:
    """Return the exact title/section encoded by a current official URL."""

    try:
        parsed = urlparse(str(source_url or ""))
    except Exception:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "legislature.maine.gov"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = _OFFICIAL_SECTION_PATH_RE.fullmatch(parsed.path or "")
    if match is None:
        return None
    return match.group("title"), match.group("section")


def _source_section_matches_visible(source_section: str, visible_section: str) -> bool:
    """Accept an exact identity or Maine's official ``-N`` variant suffix."""

    source = str(source_section or "").strip()
    visible = str(visible_section or "").strip()
    if not source or not visible:
        return False
    if source.casefold() == visible.casefold():
        return True
    return bool(
        re.fullmatch(
            rf"{re.escape(visible)}-[1-9][0-9]*",
            source,
            flags=re.IGNORECASE,
        )
    )


def _source_bound_mrs_section_identity(
    soup: object,
    *,
    source_url: str,
) -> Optional[Tuple[object, str, str, str]]:
    """Bind an MRS container to its official URL and visible page identity."""

    locator = _official_section_locator(source_url)
    find_all = getattr(soup, "find_all", None)
    select = getattr(soup, "select", None)
    if locator is None or not callable(find_all) or not callable(select):
        return None
    source_title, source_section = locator
    sections = [
        node
        for node in find_all("div")
        if "MRSSection" in _node_classes(node)
    ]
    if len(sections) != 1:
        return None
    section_node = sections[0]
    if "status_current" not in _node_classes(section_node):
        return None
    headings = [
        node
        for node in section_node.find_all(recursive=False)
        if "heading_section" in _node_classes(node)
    ]
    if len(headings) != 1:
        return None
    heading_match = _SEC_RE.fullmatch(_clean(headings[0].get_text(" ")))
    if heading_match is None:
        return None
    visible_section = heading_match.group("num")
    if not _source_section_matches_visible(source_section, visible_section):
        return None

    title_node = getattr(soup, "title", None)
    document_title = _clean(title_node.get_text(" ")) if title_node is not None else ""
    document_match = _DOCUMENT_TITLE_RE.fullmatch(document_title)
    visible_titles = list(select(".MRSTitle"))
    visible_title_match = (
        _VISIBLE_TITLE_RE.match(_clean(visible_titles[0].get_text(" ")))
        if len(visible_titles) == 1
        else None
    )
    if document_match is None or visible_title_match is None:
        return None
    if not (
        document_match.group("title").casefold()
        == visible_title_match.group("title").casefold()
        == source_title.casefold()
    ):
        return None
    if document_match.group("section").casefold() != visible_section.casefold():
        return None
    return section_node, source_title, source_section, visible_section


def _headnote_kind(text: str) -> Optional[str]:
    # The official publisher occasionally leaves layout whitespace directly
    # before a terminal marker's closing parenthesis.  Normalize only that
    # punctuation boundary; the known complete-marker grammars below remain
    # unchanged and incidental prose still cannot become terminal evidence.
    value = re.sub(r"\s+\)$", ")", _clean(text))
    if value == "(REPEALED)":
        return "repealed"
    if value == "(PLACEHOLDER)":
        return "placeholder"
    reallocated = _REALLOCATED_HEADNOTE_RE.fullmatch(value)
    if reallocated is not None:
        return f"reallocated_{reallocated.group('direction').lower()}"
    if _CONTINGENT_REPEAL_HEADNOTE_RE.fullmatch(value):
        return "repealed_on_contingency"
    if _CONFLICT_REPEAL_HEADNOTE_RE.fullmatch(value):
        return "repealed_conflict_variant"
    if value in _EXACT_SPECIAL_REPEAL_HEADNOTES:
        return "repealed_special_caption"
    return None


def _source_bound_maine_section_disposition_from_soup(
    soup: object,
    *,
    source_url: str,
) -> Optional[str]:
    """Classify an exact official nonoperative MRS section page.

    Classification is structural and source-bound.  Incidental words such as
    ``repealed`` in operative statutory text are never treated as a terminal.
    """

    identity = _source_bound_mrs_section_identity(soup, source_url=source_url)
    if identity is None:
        return None
    section_node, source_title, source_section, visible_section = identity
    children = list(section_node.find_all(recursive=False))
    histories = [node for node in children if "qhistory" in _node_classes(node)]
    headnote_nodes = [
        node for node in children if "headnote_blip" in _node_classes(node)
    ]
    note_text = _clean(
        " ".join(
            node.get_text(" ")
            for node in children
            if "note" in _node_classes(node)
        )
    )
    if not histories:
        note_contract = _EXACT_NOTE_ONLY_TERMINALS.get(
            (source_title.casefold(), source_section.casefold())
        )
        unexpected_text = [
            _clean(node.get_text(" "))
            for node in children
            if not (
                {"heading_section", "note"} & _node_classes(node)
                or "MRSSection" in _node_classes(node)
            )
            and _clean(node.get_text(" ")) not in {"", "."}
        ]
        if (
            note_contract is not None
            and not headnote_nodes
            and not unexpected_text
            and visible_section.casefold() == note_contract[0].casefold()
            and hashlib.sha256(note_text.encode("utf-8")).hexdigest()
            == note_contract[1]
        ):
            return note_contract[2]
        return None
    if len(histories) != 1:
        return None
    history = _clean(histories[0].get_text(" "))
    if not history.startswith("SECTION HISTORY "):
        return None

    heading_node = next(
        node for node in children if "heading_section" in _node_classes(node)
    )
    heading_match = _SEC_RE.fullmatch(_clean(heading_node.get_text(" ")))
    if heading_match is None:
        return None
    heading_name = _clean(heading_match.group("head"))

    headnote_texts: list[str] = []
    body_texts: list[str] = []
    for node in children:
        classes = _node_classes(node)
        text = _clean(node.get_text(" "))
        if "heading_section" in classes or "qhistory" in classes:
            continue
        if "headnote_blip" in classes:
            if text:
                headnote_texts.append(text)
            continue
        if "note" in classes:
            continue
        if text and text != ".":
            body_texts.append(text)

    marker_kinds: list[str] = []
    dated_contract = _EXACT_DATED_REPEAL_HEADNOTES.get(
        (source_title.casefold(), source_section.casefold())
    )
    if (
        dated_contract is not None
        and headnote_texts == [dated_contract[0]]
    ):
        marker_kinds.append(dated_contract[1])
    else:
        for headnote in headnote_texts:
            kind = _headnote_kind(headnote)
            if kind is None:
                return None
            marker_kinds.append(kind)

    # Older/synthetic official layouts may place the exact marker in the
    # heading or as the only direct body node.  Require it to be the complete
    # marker, never merely a word found inside operative text.
    if not headnote_texts and not body_texts and (
        heading_name == "(REPEALED)" or heading_name.endswith(" (REPEALED)")
    ):
        marker_kinds.append("repealed")
    elif not headnote_texts and body_texts == ["(REPEALED)"]:
        marker_kinds.append("repealed")
        body_texts = []

    if body_texts:
        return None
    if marker_kinds:
        kinds = set(marker_kinds)
        if "repealed_conflict_variant" in kinds and kinds <= {
            "repealed",
            "repealed_conflict_variant",
        }:
            return "repealed_conflict_variant"
        if "repealed_on_contingency" in kinds and kinds <= {
            "repealed",
            "repealed_on_contingency",
        }:
            return "repealed_on_contingency"
        if "repealed_special_caption" in kinds and kinds <= {
            "repealed",
            "repealed_special_caption",
        }:
            return "repealed"
        if "repealed" in kinds and all(
            kind == "repealed" or kind.startswith("reallocated_")
            for kind in kinds
        ):
            return "repealed"
        if kinds and all(kind.startswith("reallocated_") for kind in kinds):
            directions = {kind.rsplit("_", 1)[-1] for kind in kinds}
            return (
                f"reallocated_{next(iter(directions))}"
                if len(directions) == 1
                else "reallocated"
            )
        if kinds == {"placeholder"}:
            return "placeholder"
        if kinds == {"repealed_effective_dated"}:
            return "repealed_effective_dated"
        return None

    history_contract = _EXACT_HISTORY_ONLY_TERMINALS.get(
        (source_title.casefold(), source_section.casefold())
    )
    if history_contract is None:
        return None
    expected_visible_section, expected_history_sha256, disposition = history_contract
    if visible_section.casefold() != expected_visible_section.casefold():
        return None
    if hashlib.sha256(history.encode("utf-8")).hexdigest() != expected_history_sha256:
        return None
    return disposition


def source_bound_maine_section_disposition(
    html: str,
    *,
    source_url: str,
) -> Optional[str]:
    """Classify an exact official nonoperative MRS section page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    return _source_bound_maine_section_disposition_from_soup(
        soup,
        source_url=source_url,
    )


def source_bound_maine_chapter_disposition(
    html: str,
    *,
    source_url: str,
    title_catalog_label: str,
) -> Optional[str]:
    """Classify an exact official empty chapter from its title-catalog note."""

    try:
        parsed = urlparse(str(source_url or ""))
    except Exception:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "legislature.maine.gov"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    locator = _OFFICIAL_CHAPTER_PATH_RE.fullmatch(parsed.path or "")
    if locator is None or locator.group("chapter") == "0":
        return None
    contract = _EXACT_EMPTY_CHAPTER_TERMINALS.get(
        (locator.group("title").casefold(), locator.group("chapter").casefold())
    )
    if contract is None:
        return None
    expected_label_sha256, expected_heading, disposition = contract
    if (
        hashlib.sha256(_clean(title_catalog_label).encode("utf-8")).hexdigest()
        != expected_label_sha256
    ):
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select(".MRSSection"):
        return None
    section_links = [
        str(anchor.get("href") or "").strip()
        for anchor in soup.find_all("a", href=True)
        if re.search(
            r"title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$",
            str(anchor.get("href") or "").strip(),
            re.IGNORECASE,
        )
        and not str(anchor.get("href") or "").strip().lower().endswith(
            "sec0.html"
        )
    ]
    if section_links:
        return None
    title_node = getattr(soup, "title", None)
    document_title = (
        _clean(title_node.get_text(" ")) if title_node is not None else ""
    )
    headings = list(soup.select(".ch_heading"))
    if (
        len(headings) != 1
        or document_title != expected_heading
        or _clean(headings[0].get_text(" ")) != expected_heading
    ):
        return None
    return disposition


def parse_maine_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Maine Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    if (
        _source_bound_maine_section_disposition_from_soup(
            soup,
            source_url=source_url,
        )
        is not None
    ):
        return None
    sec = soup.find("div", class_=re.compile(r"MRSSection"))
    if sec is None:
        return None
    heading = ""
    paras: list[str] = []
    substantive_paras: list[str] = []
    for element in sec.find_all(recursive=False):
        classes = " ".join(element.get("class") or [])
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if "heading_section" in classes:
            heading = text
            continue
        if "qhistory" in classes:
            continue
        paras.append(text)
        if "headnote_blip" not in classes and "note" not in classes:
            substantive_paras.append(text)
    body = _clean(" ".join(paras))
    substantive_body = _clean(" ".join(substantive_paras))
    identity = _source_bound_mrs_section_identity(soup, source_url=source_url)
    if not substantive_body and identity is not None:
        _section_node, source_title, source_section, visible_section = identity
        note_contract = _EXACT_NOTE_ONLY_OPERATIVE_SECTIONS.get(
            (source_title.casefold(), source_section.casefold())
        )
        note_text = _clean(
            " ".join(
                element.get_text(" ")
                for element in sec.find_all(recursive=False)
                if "note" in _node_classes(element)
            )
        )
        if (
            note_contract is not None
            and visible_section.casefold() == note_contract[0].casefold()
            and hashlib.sha256(note_text.encode("utf-8")).hexdigest()
            == note_contract[1]
        ):
            substantive_body = note_text
    if not substantive_body or not re.search(r"[0-9A-Za-z]", substantive_body):
        return None
    if len(substantive_body) < 40:
        statutory_body_node = any(
            (
                "mrs-text" in _node_classes(element)
                or any(name.startswith("MRS") for name in _node_classes(element))
            )
            and _clean(element.get_text(" "))
            for element in sec.find_all(recursive=False)
        )
        if identity is None or not statutory_body_node:
            return None
    headnote_kinds = [
        _headnote_kind(_clean(element.get_text(" ")))
        for element in sec.find_all(recursive=False)
        if "headnote_blip" in _node_classes(element)
    ]
    if any(
        kind is not None and kind != "reallocated_from"
        for kind in headnote_kinds
    ):
        # ``REALLOCATED FROM`` identifies operative text at its new official
        # locator and is retained with that context.  Other exact terminal
        # signals accompanied by body text are semantic drift and fail closed.
        return None
    url_match = _TITLE_RE.search(source_url or "")
    title = url_match.group("title") if url_match else ""
    number = url_match.group("section") if url_match else ""
    head_match = _SEC_RE.search(heading)
    if head_match:
        number = number or head_match.group("num")
        name = head_match.group("head").strip()
    else:
        name = heading or f"Section {number}"
    if not number:
        return None
    official_cite = (
        f"Me. Rev. Stat. tit. {title}, § {number}"
        if title
        else f"Me. Rev. Stat. § {number}"
    )
    return NormalizedStatute(
        state_code="ME",
        state_name="Maine",
        # Maine section numbers are only unique within a title.  Binding the
        # title into the canonical ID prevents (for example) title 1 § 1
        # from suppressing title 17-A § 1 during checkpoint replay or final
        # corpus deduplication.
        statute_id=f"{code_name} {official_cite}",
        code_name=code_name,
        title_number=title or None,
        section_number=number,
        section_name=name[:200],
        full_text=body,
        source_url=source_url or f"{BASE}/",
        official_cite=official_cite,
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_maine_mrs_section",
            "source_authority_class": "official",
            "discovery_method": "legislature_mrssection",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MAINE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def title_toc_chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Chapter index URLs from a title TOC (``MRSChapter_toclist``).

    Adapted from Vaquill-AI/open-us-law ``scrape_me2`` nested title listing.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin, urlparse

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    containers = soup.find_all("div", class_=re.compile(r"MRSChapter_toclist"))
    anchors = []
    for container in containers:
        anchors.extend(container.find_all("a", href=True))
    if not anchors:
        anchors = soup.find_all("a", href=True)
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        if not re.search(r"title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", href, re.IGNORECASE):
            continue
        if href.lower().endswith("ch0sec0.html"):
            continue
        base_text = str(base_url or BASE).strip()
        base_path = str(urlparse(base_text).path or "")
        # A caller may supply either the statutes directory or the exact title
        # index document.  Appending ``/`` to a document URL turns relative
        # chapter links into bogus children such as
        # ``...ch0sec0.html/title1ch1sec0.html`` and can multiply futile
        # archive requests.  Preserve normal RFC URL-join file semantics for
        # HTML documents while retaining directory semantics for the default.
        join_base = (
            base_text
            if re.search(r"\.html?$", base_path, re.IGNORECASE)
            else base_text.rstrip("/") + "/"
        )
        url = urljoin(join_base, href)
        if url in seen:
            continue
        seen.add(url)
        name = _clean(anchor.get_text(" ")) or url
        out.append((url, name))
    return out


def configured_title_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MAINE_TITLE_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_title_toc_html() -> List[Tuple[str, str]]:
    path = configured_title_toc_html_path()
    if path is None:
        return []
    return title_toc_chapter_links(path.read_text(encoding="utf-8", errors="replace"))
