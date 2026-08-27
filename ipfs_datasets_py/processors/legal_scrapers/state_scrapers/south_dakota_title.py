"""Official South Dakota whole-title HTML parser.

Adapted from Vaquill-AI/open-us-law ``sd_bulk.parse`` (Apache-2.0).
``sdlegislature.gov/api/Statutes/{title}.html?all=true`` carries every section
heading (SENU span) plus body. Local paths: ``SOUTH_DAKOTA_TITLE_HTML``,
``SOUTH_DAKOTA_CHAPTER_HTML``. Title/chapter ``?all=true`` responses may be
UTF-16 LE without a BOM (Vaquill ``scrapeSD._decode``).
"""

from __future__ import annotations

import os
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

SECTION_NUM_RE = re.compile(
    r"^(\d+[A-Za-z]*-\d+[A-Za-z]*-\d+[A-Za-z0-9]*(?:\.\d+)*"
    r"(?:\([A-Za-z0-9]+\))*)"
)
_CLASS_HEADING_RE = re.compile(r"(?:Normal|StatuteNumber1)$")
_CLASS_TOC_RE = re.compile(r"B$")
_SOURCE_RE = re.compile(r"^Source:", re.IGNORECASE)
# Whole-title bundles carry generated ``s<hex>`` style families; exact
# single-section fallback pages use the stable ``pt-`` family instead.
_HASH_RE = re.compile(r"^(s[0-9a-f]+|pt-)")
_WS = re.compile(r"\s+")
_TERMINAL_PATTERNS = tuple(
    (
        disposition,
        re.compile(pattern, re.IGNORECASE),
    )
    for disposition, pattern in (
        (
            "repealed",
            r"\[\s*(?:repealed(?:\s+and\s+transferred)?|"
            r"transferred\s+and\s+repealed)\s*\]|"
            r"(?:^|[.;]\s*)repealed(?=\s+by\b|\s*[.\];,]|\s*$)|"
            r"\brepealed\s+(?:by\s+)?(?:SL|SDCL)\b|"
            r"\brepealed\s*[.;]?\s*$",
        ),
        (
            "reserved",
            r"\[\s*reserved\s*\]|"
            r"(?:^|[.;]\s*)reserved(?=\s*[.\];,]|\s*$)|"
            r"\breserved\s*[.;]?\s*$",
        ),
        (
            "expired",
            r"\[\s*expired\s*\]|\bexpired\s+on\b|"
            r"(?:^|[.;]\s*)expired(?=\s*[.\];,]|\s*$)",
        ),
        (
            "transferred",
            r"\[\s*transferred\s*\]|"
            r"(?:^|[.;]\s*)transferred(?=\s+to\b|\s*[.\];,]|\s*$)|"
            r"\btransferred\s*[.;]?\s*$",
        ),
        (
            "obsolete",
            r"\[\s*obsolete\s*\]|\btemporary\s+and\s+obsolete\b|"
            r"(?:^|[.;]\s*)obsolete(?=\s*[.\];,]|\s*$)",
        ),
        (
            "omitted",
            r"\[\s*omitted(?:\s+as\s+obsolete)?\s*\]|"
            r"(?:^|[.;]\s*)omitted(?=\s+as\s+obsolete\b|\s*[.\];,]|\s*$)",
        ),
        (
            "executed",
            r"\[\s*executed\s*\]|"
            r"(?:^|[.;]\s*)executed(?=\s*[.\];,]|\s*$)|"
            r"\bexecuted\s*[.;]?\s*$",
        ),
        (
            "superseded",
            r"\[\s*superseded\s*\]|\bsuperseded\s+eff\.|"
            r"(?:^|[.;]\s*)superseded(?=\s+by\b|\s*[.\];,]|\s*$)",
        ),
        (
            "rejected",
            r"\[\s*rejected\s*\]|"
            r"(?:^|[.;]\s*)rejected(?=\s+by\b|\s*[.\];,]|\s*$)",
        ),
        (
            "unconstitutional",
            r"\bunconstitutional\s*[.;]?\s*$",
        ),
        (
            "not_implemented",
            r"\bnot\s+implemented\s*[.;]?\s*$",
        ),
        (
            "abolished",
            r"\[\s*abolished\s*\]|"
            r"(?:^|[.;]\s*)abolished(?=\s*[.\];,]|\s*$)",
        ),
    )
)


def title_from_section(section_number: str) -> str:
    parts = str(section_number or "").split("-")
    if len(parts) < 3 or not parts[0]:
        return ""
    return parts[0]


def chapter_from_section(section_number: str) -> str:
    parts = str(section_number or "").split("-")
    if len(parts) < 3 or not parts[1]:
        return ""
    return parts[1]


def title_html_url(title: str) -> str:
    return f"https://sdlegislature.gov/api/Statutes/{title}.html?all=true"


def chapter_html_url(title: str, chapter: str) -> str:
    return f"https://sdlegislature.gov/api/Statutes/{title}-{chapter}.html?all=true"


def section_html_url(section_number: str) -> str:
    return (
        "https://sdlegislature.gov/api/Statutes/"
        f"{section_number}.html?all=true"
    )


def decode_sdlegislature_bytes(raw: bytes) -> str:
    """Decode SDLRC ``?all=true`` payloads (UTF-16 LE without BOM, else UTF-8)."""

    data = raw or b""
    if len(data) >= 2 and data[1] == 0x00:
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_CHAPTER_ENTRY_RE = re.compile(r"^(\d+(?:[A-Z](?=[A-Z]))?)(.+)$")
_CHAPTER_QUERY_IDENTITY_RE = re.compile(
    r"^(?P<title>\d+[A-Za-z]*)-(?P<chapter>\d+[A-Za-z]*)$"
)
_LEADING_ZEROS_RE = re.compile(r"^0+(\d+[A-Za-z]*)$")


def normalize_chapter_number(display: str) -> str:
    match = _LEADING_ZEROS_RE.match(str(display or ""))
    return match.group(1) if match else str(display or "")


def title_chapter_entries(
    html: str,
    *,
    title_label: str = "",
) -> List[Tuple[str, str]]:
    """Chapter numbers/names from a title ``?all=true`` TOC.

    Current official pages concatenate the title TOC and each chapter document.
    Both levels contain paragraphs whose class ends in ``B``.  The title-level
    links are therefore the source of authority: they end in
    ``/Statutes/{title}-{chapter}``, while section links use ``Statute=`` query
    identities.  The text-only fallback preserves support for retained legacy
    fixtures which predate those links.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    source = html or ""
    first_document_end = re.search(r"</html\s*>", source, re.IGNORECASE)
    if first_document_end is not None:
        source = source[: first_document_end.end()]
    soup = BeautifulSoup(source, "html.parser")
    out: List[Tuple[str, str]] = []
    structured_links_seen = False

    def _validate_occurrences(
        entries: List[Tuple[str, str]],
    ) -> List[Tuple[str, str]]:
        grouped: Dict[str, List[str]] = {}
        for identity, label in entries:
            grouped.setdefault(identity, []).append(label)
        for identity, labels in grouped.items():
            if len(labels) == 1:
                continue
            dispositions = [source_bound_terminal_disposition(label) for label in labels]
            if (
                len(labels) == 2
                and len(set(labels)) == 2
                and sum(bool(value) for value in dispositions) == 1
            ):
                continue
            raise ValueError(
                "South Dakota title TOC repeated unresolved chapter identity: "
                f"{identity}; labels={labels!r}"
            )
        return entries

    def _following_anchor_label(anchor: Any) -> str:
        pieces: List[str] = []
        for sibling in anchor.next_siblings:
            if getattr(sibling, "name", None) == "a":
                break
            if hasattr(sibling, "get_text"):
                value = sibling.get_text(" ", strip=True)
            else:
                value = str(sibling)
            if _clean(value):
                pieces.append(value)
        return re.sub(r"^[.\s\u00a0:;\-]+", "", _clean(" ".join(pieces)))

    for para in soup.find_all("p"):
        for anchor in para.find_all("a", href=True):
            # Some retained title catalogs contain invalid nested ``p``
            # wrappers. Parse an anchor only through its nearest paragraph so
            # an outer wrapper cannot count the same source row a second time.
            if anchor.find_parent("p") is not para:
                continue
            chapter_identity = ""
            chapter_display = ""
            parsed = urlparse(str(anchor.get("href") or ""))
            match = re.search(
                r"/Statutes/(?P<title>\d+[A-Za-z]*)-"
                r"(?P<chapter>\d+[A-Za-z]*)/?$",
                parsed.path,
                re.IGNORECASE,
            )
            query_path = parsed.path.rstrip("/").casefold()
            if match is None and query_path in {
                "/statutes",
                "/statutes/displaystatute.aspx",
                "/statutes/codified_laws/displaystatute.aspx",
            }:
                query = {
                    str(key).casefold(): values
                    for key, values in parse_qs(parsed.query).items()
                }
                statute_values = query.get("statute") or []
                type_values = query.get("type") or []
                legacy_query_valid = query_path == "/statutes" or (
                    len(type_values) == 1
                    and str(type_values[0]).casefold() == "statute"
                )
                if legacy_query_valid and len(statute_values) == 1:
                    match = _CHAPTER_QUERY_IDENTITY_RE.fullmatch(
                        _clean(statute_values[0])
                    )
            if match is None:
                continue
            if title_label and match.group("title").casefold() != str(
                title_label
            ).casefold():
                continue
            structured_links_seen = True
            chapter_identity = normalize_chapter_number(match.group("chapter"))
            chapter_display = _clean(anchor.get_text(" ", strip=True))
            if chapter_display:
                displayed_identity = normalize_chapter_number(chapter_display)
                if displayed_identity.casefold() != chapter_identity.casefold():
                    raise ValueError(
                        "South Dakota chapter TOC link/display identity mismatch: "
                        f"link={chapter_identity!r} display={chapter_display!r}"
                    )
            name = _following_anchor_label(anchor)
            out.append((chapter_identity, name or f"Chapter {chapter_identity}"))
    if structured_links_seen:
        return _validate_occurrences(out)

    # Retained Vaquill-era fixtures only preserve rendered TOC text.
    for para in soup.find_all("p"):
        cls_list = para.get("class") or []
        if not cls_list or not str(cls_list[0]).endswith("B"):
            continue
        raw = _clean(para.get_text(strip=True))
        if not raw:
            continue
        match = _CHAPTER_ENTRY_RE.match(raw)
        if not match:
            continue
        number = normalize_chapter_number(match.group(1))
        if not number:
            continue
        name = match.group(2).strip() or f"Chapter {number}"
        out.append((number, name))
    return _validate_occurrences(out)


def title_section_entries(html: str, *, title_label: str) -> List[Tuple[str, str]]:
    """Return exact section inventory identities embedded in a whole-title page.

    SDLRC currently emits three retained official variants in a single title
    response: one ``B`` paragraph per section, a legacy classless paragraph
    containing one or more section links, and section-heading-only chapter documents.
    Prefer the first inventory occurrence and use the heading as the official
    fallback when a chapter has no separate TOC.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()

    def _anchor_section_number(anchor: Any) -> str:
        parsed = urlparse(str(anchor.get("href") or ""))
        query = parse_qs(parsed.query)
        query_number = (query.get("Statute") or query.get("statute") or [""])[0]
        candidate = query_number or anchor.get_text(" ", strip=True)
        match = SECTION_NUM_RE.match(_clean(candidate))
        if match is None:
            return ""
        number = match.group(1)
        return number if number.split("-")[0] == str(title_label) else ""

    def _append(section_number: str, label: str) -> None:
        if not section_number or section_number in seen:
            return
        seen.add(section_number)
        cleaned_label = _clean(label)
        name = re.sub(
            r"^" + re.escape(section_number) + r"\.?(?:\s+|$)",
            "",
            cleaned_label,
        ).strip()
        out.append((section_number, name or f"Section {section_number}"))

    def _following_anchor_label(anchor: Any, section_number: str) -> str:
        pieces = [section_number]
        for sibling in anchor.next_siblings:
            if getattr(sibling, "name", None) == "a":
                break
            if hasattr(sibling, "get_text"):
                value = sibling.get_text(" ", strip=True)
            else:
                value = str(sibling)
            if _clean(value):
                pieces.append(value)
        label = _clean(" ".join(pieces))
        return re.split(
            r"\s+(?=PART\s+\d+[A-Za-z]*\.)",
            label,
            maxsplit=1,
        )[0].strip()

    for para in soup.find_all("p"):
        classes = para.get("class") or []
        anchors = [
            (anchor, _anchor_section_number(anchor))
            for anchor in para.find_all("a", href=True)
        ]
        anchors = [(anchor, number) for anchor, number in anchors if number]
        is_b_toc = bool(classes and str(classes[0]).endswith("B"))
        if is_b_toc and anchors:
            _append(anchors[0][1], para.get_text(" ", strip=True))
            continue
        if not classes and anchors:
            plain = _clean(para.get_text(" ", strip=True))
            if len(anchors) == 1:
                section_number = anchors[0][1]
                if (
                    re.match(
                        r"^" + re.escape(section_number) + r"(?:[.,\s]|$)",
                        plain,
                    )
                    is None
                    or not source_bound_terminal_disposition(plain)
                ):
                    continue
            for anchor, section_number in anchors:
                _append(
                    section_number,
                    _following_anchor_label(anchor, section_number),
                )
            continue
        if not classes or not str(classes[0]).endswith("Normal"):
            continue
        plain = _clean(para.get_text(" ", strip=True))
        if not SECTION_NUM_RE.match(plain):
            continue
        section_number = ""
        for span in para.find_all("span"):
            if "SENU" not in " ".join(span.get("class") or []):
                continue
            match = SECTION_NUM_RE.match(_clean(span.get_text(" ", strip=True)))
            if match is not None:
                section_number = match.group(1)
                break
        if not section_number and anchors:
            section_number = anchors[0][1]
        if section_number.split("-")[0] == str(title_label):
            _append(section_number, plain)
    return out


def _clean(raw: str) -> str:
    return _WS.sub(" ", (raw or "").replace("\xa0", " ")).strip()


def source_bound_terminal_disposition(label: str) -> str:
    """Return the exact source-marked terminal disposition, if any."""

    cleaned = _clean(label)
    for disposition, pattern in _TERMINAL_PATTERNS:
        if pattern.search(cleaned) is not None:
            return disposition
    return ""


def parse_south_dakota_title_html_with_dispositions(
    html: str,
    *,
    title_label: str,
    code_name: str = "South Dakota Codified Laws",
    max_statutes: Optional[int] = None,
    source_url: str = "",
) -> Tuple[List[NormalizedStatute], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse a whole official title and account for every section heading.

    Returns operative statutes, source-marked terminal units, and unresolved
    headings.  Strict full-corpus callers reject a non-empty unresolved list;
    the compatibility wrapper below preserves the historical rows-only API.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], [], [{"reason": "beautifulsoup_unavailable"}]
    statutes: List[NormalizedStatute] = []
    terminal_units: List[Dict[str, Any]] = []
    unresolved_units: List[Dict[str, Any]] = []
    occurrences: List[Dict[str, Any]] = []
    source = html or ""
    documents: List[str] = []
    cursor = 0
    for closing in re.finditer(r"</html\s*>", source, re.IGNORECASE):
        document = source[cursor : closing.end()]
        cursor = closing.end()
        if "<html" in document.casefold():
            documents.append(document)
    remainder = source[cursor:]
    if "<html" in remainder.casefold():
        documents.append(remainder)
    if not documents:
        documents = [source]

    for document_index, document in enumerate(documents):
        soup = BeautifulSoup(document, "html.parser")
        document_occurrence_start = len(occurrences)
        document_url = ""
        for meta in soup.find_all("meta"):
            if str(meta.get("property") or "").casefold() == "og:url":
                document_url = str(meta.get("content") or "").strip()
                break
        document_sha256 = hashlib.sha256(document.encode("utf-8")).hexdigest()
        cur_hash = cur_num = cur_name = None
        cur_body: List[str] = []
        cur_source_evidence: List[str] = []

        def _flush_document_occurrence() -> None:
            if not cur_num:
                return
            occurrences.append(
                {
                    "section_number": cur_num,
                    "source_label": _clean(cur_name or f"Section {cur_num}"),
                    "body": " ".join(cur_body).strip(),
                    "document_index": document_index,
                    "document_url": document_url,
                    "decoded_document_sha256": document_sha256,
                    "source_evidence": list(cur_source_evidence),
                }
            )

        for para in soup.find_all("p"):
            cls_list = para.get("class", []) or []
            if not cls_list:
                continue
            cls = cls_list[0]
            if _CLASS_TOC_RE.search(cls):
                continue
            cls_hash_match = _HASH_RE.match(cls)
            cls_hash = cls_hash_match.group(1) if cls_hash_match else None
            if cls_hash is None:
                continue
            plain = _clean(para.get_text(" ", strip=True))
            if _SOURCE_RE.match(plain):
                if cur_num is not None:
                    cur_source_evidence.append(plain)
                continue
            if _CLASS_HEADING_RE.search(cls):
                sec_num = None
                senu_parts = [
                    _clean(span.get_text(" ", strip=True))
                    for span in para.find_all("span")
                    if "SENU" in " ".join(span.get("class", []) or [])
                ]
                if senu_parts:
                    senu_identity_text = senu_parts[0]
                    for continuation in senu_parts[1:]:
                        parenthetical = re.match(
                            r"^((?:\([A-Za-z0-9]+\))+)",
                            continuation,
                        )
                        if parenthetical is None:
                            break
                        senu_identity_text += parenthetical.group(1)
                    match = SECTION_NUM_RE.match(senu_identity_text)
                    if match:
                        sec_num = match.group(1)
                if sec_num is None:
                    for anchor in para.find_all("a", href=True):
                        query = {
                            str(key).casefold(): values
                            for key, values in parse_qs(
                                urlparse(anchor["href"]).query
                            ).items()
                        }
                        num = (query.get("statute") or [""])[0]
                        match = SECTION_NUM_RE.match(num)
                        if match:
                            sec_num = match.group(1)
                            break
                heading_plain = re.sub(
                    r"\s+(?=\([A-Za-z0-9]+\))",
                    "",
                    plain,
                )
                if (
                    sec_num
                    and SECTION_NUM_RE.match(heading_plain)
                    and sec_num.split("-")[0] == str(title_label)
                ):
                    _flush_document_occurrence()
                    cur_hash = cls_hash
                    cur_num = sec_num
                    cur_name = re.sub(
                        r"^" + re.escape(sec_num) + r"\s*\.?\s*",
                        "",
                        heading_plain,
                    ).strip()
                    cur_body = []
                    cur_source_evidence = []
                    continue
            if cls_hash != cur_hash or cur_num is None:
                continue
            if plain:
                cur_body.append(plain)
        _flush_document_occurrence()
        if len(occurrences) == document_occurrence_start:
            description = ""
            for meta in soup.find_all("meta"):
                if str(meta.get("name") or "").casefold() == "description":
                    description = _clean(str(meta.get("content") or ""))
                    break
            description_prefix = re.sub(
                r"^South\s+Dakota\s+Codified\s+Laws\s+",
                "",
                description,
                flags=re.IGNORECASE,
            )
            legacy_match = SECTION_NUM_RE.match(description_prefix)
            legacy_number = legacy_match.group(1) if legacy_match else ""
            body_node = soup.body
            body_plain = _clean(
                body_node.get_text(" ", strip=True) if body_node is not None else ""
            )
            if (
                legacy_number
                and legacy_number.split("-")[0] == str(title_label)
                and re.match(
                    r"^" + re.escape(legacy_number) + r"(?:[.\s]|$)",
                    body_plain,
                    flags=re.IGNORECASE,
                )
                is not None
            ):
                legacy_text = re.sub(
                    r"^" + re.escape(legacy_number) + r"\s*\.?\s*",
                    "",
                    body_plain,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
                source_evidence: List[str] = []
                source_match = re.search(
                    r"\bSource:\s*",
                    legacy_text,
                    flags=re.IGNORECASE,
                )
                if source_match is not None:
                    source_evidence = [legacy_text[source_match.start() :].strip()]
                    legacy_text = legacy_text[: source_match.start()].strip()
                if source_bound_terminal_disposition(legacy_text):
                    continue
                legacy_label = legacy_text
                legacy_body = ""
                label_boundary = re.search(r"\.(?=\s*[A-Z])", legacy_text)
                if label_boundary is not None:
                    legacy_label = legacy_text[: label_boundary.end()].strip()
                    legacy_body = legacy_text[label_boundary.end() :].strip()
                occurrences.append(
                    {
                        "section_number": legacy_number,
                        "source_label": legacy_label,
                        "body": legacy_body,
                        "document_index": document_index,
                        "document_url": document_url,
                        "decoded_document_sha256": document_sha256,
                        "source_evidence": source_evidence,
                    }
                )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for occurrence in occurrences:
        grouped.setdefault(str(occurrence["section_number"]), []).append(occurrence)

    for section_number, variants in grouped.items():
        selected = variants[0]
        if len(variants) > 1:
            canonical_url = f"https://sdlegislature.gov/Statutes/{section_number}"
            canonical_variants = [
                variant
                for variant in variants
                if str(variant.get("document_url") or "").rstrip("/")
                == canonical_url
            ]
            noncanonical_variants = [
                variant for variant in variants if variant not in canonical_variants
            ]
            if (
                len(canonical_variants) != 1
                or any(
                    str(variant.get("document_url") or "").strip()
                    for variant in noncanonical_variants
                )
            ):
                raise ValueError(
                    "South Dakota repeated section variants lack one exact "
                    "canonical-current selector: "
                    f"{section_number}; variants={variants!r}"
                )
            selected = canonical_variants[0]
            for variant in noncanonical_variants:
                terminal_units.append(
                    {
                        "frontier_level": "section_lifecycle_variant",
                        "title_number": section_number.split("-")[0],
                        "chapter_number": chapter_from_section(section_number),
                        "section_number": section_number,
                        "source_label": str(variant["source_label"]),
                        "source_url": source_url or title_html_url(title_label),
                        "disposition": "noncurrent_temporal_variant",
                        "canonical_current_document_url": canonical_url,
                        "variant_document_url": "",
                        "decoded_document_sha256": str(
                            variant["decoded_document_sha256"]
                        ),
                        "source_evidence": list(variant["source_evidence"]),
                    }
                )

        parts = section_number.split("-")
        source_label = str(selected["source_label"])
        disposition = source_bound_terminal_disposition(source_label)
        if disposition:
            terminal_units.append(
                {
                    "frontier_level": "section",
                    "title_number": parts[0] if parts else str(title_label),
                    "chapter_number": parts[1] if len(parts) > 1 else "",
                    "section_number": section_number,
                    "source_label": source_label,
                    "source_url": source_url or title_html_url(title_label),
                    "disposition": disposition,
                }
            )
            continue
        body = str(selected["body"])
        if len(body) < 20:
            child_identities = sorted(
                identity
                for identity in grouped
                if identity.startswith(f"{section_number}(")
            )
            if child_identities:
                terminal_units.append(
                    {
                        "frontier_level": "section_source_status",
                        "title_number": parts[0] if parts else str(title_label),
                        "chapter_number": parts[1] if len(parts) > 1 else "",
                        "section_number": section_number,
                        "source_label": source_label,
                        "source_url": source_url or title_html_url(title_label),
                        "disposition": "source_collection_parent",
                        "child_identity_count": len(child_identities),
                        "child_identities_sha256": hashlib.sha256(
                            "\n".join(child_identities).encode("utf-8")
                        ).hexdigest(),
                    }
                )
                continue
            unresolved_units.append(
                {
                    "frontier_level": "section",
                    "title_number": parts[0] if parts else str(title_label),
                    "chapter_number": parts[1] if len(parts) > 1 else "",
                    "section_number": section_number,
                    "source_label": source_label,
                    "source_url": source_url or title_html_url(title_label),
                    "reason": "nonterminal_section_without_substantive_body",
                }
            )
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            continue
        statutes.append(
            NormalizedStatute(
                state_code="SD",
                state_name="South Dakota",
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                title_number=parts[0] if parts else title_label,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=section_number,
                section_name=source_label[:200],
                full_text=body,
                source_url=source_url or title_html_url(title_label),
                official_cite=f"S.D. Codified Laws § {section_number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_south_dakota_title_html",
                    "source_authority_class": "official",
                    "discovery_method": "sdlegislature_statutes_all_true",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes, terminal_units, unresolved_units


def parse_south_dakota_title_html(
    html: str,
    *,
    title_label: str,
    code_name: str = "South Dakota Codified Laws",
    max_statutes: Optional[int] = None,
    source_url: str = "",
) -> List[NormalizedStatute]:
    """Compatibility rows-only projection of the exact title parser."""

    statutes, _terminal_units, _unresolved_units = (
        parse_south_dakota_title_html_with_dispositions(
            html,
            title_label=title_label,
            code_name=code_name,
            max_statutes=max_statutes,
            source_url=source_url,
        )
    )
    return statutes


def configured_title_html_path() -> Optional[Path]:
    for key in ("SOUTH_DAKOTA_TITLE_HTML", "SOUTH_DAKOTA_CHAPTER_HTML"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def parse_configured_south_dakota_title(
    *,
    code_name: str = "South Dakota Codified Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_title_html_path()
    if path is None:
        return []
    html = decode_sdlegislature_bytes(path.read_bytes())
    stem = path.stem.split(".")[0]
    title_label = stem.split("-")[0] if stem else "22"
    source = (
        chapter_html_url(title_label, stem.split("-", 1)[1])
        if "-" in stem
        else title_html_url(title_label)
    )
    return parse_south_dakota_title_html(
        html,
        title_label=title_label,
        code_name=code_name,
        max_statutes=max_statutes,
        source_url=source,
    )
