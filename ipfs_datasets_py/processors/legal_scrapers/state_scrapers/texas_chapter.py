"""Official Texas chapter HTML parser (tcss resources / zip members).

Adapted from Vaquill-AI/open-us-law ``scrapeTX.py`` (Apache-2.0).
Body lives in ``p.left``: ``Sec.`` / ``Art.`` headings open a section,
indented paragraphs are statutory text, unindented history is dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

TCAS_RESOURCES = "https://tcss.legis.texas.gov/resources"
TCAS_API = "https://tcss.legis.texas.gov/api"
STATUTE_ORIGIN = "https://statutes.capitol.texas.gov"
# TLC codeIDs from statutes.capitol.texas.gov/assets/QuickCodes.json (Vaquill scrapeTX).
TX_CODE_IDS = {
    "AG": "1",
    "AL": "2",
    "BC": "4",
    "BO": "32",
    "CN": "5",
    "CP": "6",
    "CR": "7",
    "CV": "29",
    "ED": "9",
    "EL": "10",
    "ES": "35",
    "FA": "11",
    "FI": "12",
    "GV": "13",
    "HR": "15",
    "HS": "14",
    "I1": "37",
    "IN": "17",
    "LA": "18",
    "LG": "19",
    "NR": "20",
    "OC": "21",
    "PB": "23",
    "PE": "22",
    "PR": "25",
    "PW": "26",
    "SD": "33",
    "TN": "27",
    "TX": "28",
    "UT": "16",
    "WA": "30",
    "WL": "31",
}

_SEC_RE = re.compile(r"^(Sec\.|Art\.)\s+(\d[\d.A-Z()-]*)\.", re.IGNORECASE)
_TITLE_RE = re.compile(
    r"^(?:Sec\.|Art\.)\s+[\d.\w()-]+\.\s+((?:[A-Z][A-Z\s;,\-\(\)'\"&.]+\.)+)\s*(.*)",
)
_RESERVED = re.compile(
    r"\[(?:repealed|expired|reserved|renumbered|transferred)\b|\brepealed\b",
    re.IGNORECASE,
)
_HISTORY_PREFIXES = (
    "Acts ",
    "Added by",
    "Amended by",
    "Redesignated",
    "Transferred",
    "Expired ",
    "Renumbered",
    "Reenacted",
)
_WS = re.compile(r"\s+")
_EXACT_TERMINAL = re.compile(
    r"^[\[(]?\s*(blank|repealed|expired|reserved|renumbered|transferred)\b",
    re.IGNORECASE,
)
_TEMPORAL_VARIANT = re.compile(
    r"^Text of (?P<unit>article|section|subsection) effective "
    r"(?P<kind>from|on|until) (?P<date>.+?)\.?$",
    re.IGNORECASE,
)
_AS_ADDED_VARIANT = re.compile(
    r"^Text of (?P<unit>article|section|subsection) as added by (?P<source>.+)$",
    re.IGNORECASE,
)
_CONCURRENT_VARIANT = re.compile(
    r"^(?:For|See also) another "
    r"(?P<unit>article|chapter|section|subchapter)\b.+$",
    re.IGNORECASE,
)


def chapter_html_url(code: str, chapter_num: str) -> str:
    return f"{TCAS_RESOURCES}/{code}/htm/{code}.{chapter_num}.htm"


def get_statute_array_url(code: str) -> str:
    token = str(code or "").strip().upper()
    return (
        f"{TCAS_API}/GetStatuteArray/GetStatuteArray/"
        f"{token}/{token}/null/null/null/null/null/null/null/null/htm"
    )


def populate_chapter_list_url(code: str) -> Optional[str]:
    code_id = TX_CODE_IDS.get(str(code or "").strip().upper())
    if not code_id:
        return None
    return f"{TCAS_API}/QuickSearch/PopulateChapterList/{code_id}/CH"


def _chapter_number_from_entry(entry: dict, code: str) -> str:
    url = str(entry.get("url") or "").strip()
    url_match = re.search(
        r"/" + re.escape(code) + r"\.([0-9A-Za-z._-]+?)\.htm", url, re.IGNORECASE
    )
    if url_match and url_match.group(1)[:1].isdigit():
        return url_match.group(1)
    rel = str(entry.get("url") or "").strip()
    rel_match = re.match(re.escape(code) + r"\.([0-9A-Za-z._-]+)$", rel, re.IGNORECASE)
    if rel_match and rel_match.group(1)[:1].isdigit():
        return rel_match.group(1)
    name = str(entry.get("name") or entry.get("text") or "")
    name_match = re.match(r"CHAPTER\s+([\w.]+)", name, re.IGNORECASE)
    if name_match and name_match.group(1)[:1].isdigit():
        return name_match.group(1).rstrip(".")
    return ""


def chapters_from_statute_array(payload, *, code: str) -> List[Tuple[str, str, str]]:
    """Normalize GetStatuteArray JSON to ``(chapter, name, html_url)``."""

    if not isinstance(payload, list):
        return []
    token = str(code or "").strip().upper()
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        number = _chapter_number_from_entry(entry, token)
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(entry.get("name") or f"Chapter {number}").strip()
        out.append((number, name, chapter_html_url(token, number)))
    return out


def chapters_from_quicksearch(payload, *, code: str) -> List[Tuple[str, str, str]]:
    """Normalize PopulateChapterList JSON ``{text,value,url}`` rows."""

    if not isinstance(payload, list):
        return []
    token = str(code or "").strip().upper()
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("url") or "").strip()
        number = ""
        if rel:
            rel_match = re.match(
                re.escape(token) + r"\.([0-9A-Za-z._-]+)$", rel, re.IGNORECASE
            )
            if rel_match:
                number = rel_match.group(1)
        if not number:
            number = _chapter_number_from_entry(
                {"name": entry.get("text") or "", "url": rel}, token
            )
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(entry.get("text") or f"Chapter {number}").strip()
        out.append((number, name, chapter_html_url(token, number)))
    return out


def _clean(text: str) -> str:
    return _WS.sub(
        " ", (text or "").replace("\xa0", " ").replace("\u2002", " ")
    ).strip()


def _is_history(text: str) -> bool:
    return text.startswith(_HISTORY_PREFIXES)


def _exact_terminal_disposition(heading_tail: str) -> str:
    """Classify only an explicit disposition at the start of a heading.

    Texas headings can substantively mention transferred employees or expired
    permits.  Looking for those words anywhere in a heading silently discards
    operative law, so strict closure uses only the official leading marker.
    """

    match = _EXACT_TERMINAL.match(_clean(heading_tail).strip(" ."))
    return str(match.group(1) or "").lower() if match else ""


def _strict_member_token(member_name: str) -> str:
    value = re.sub(r"\.html?$", "", str(member_name or ""), flags=re.IGNORECASE)
    value = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.").lower()
    return value or "unknown-member"


def _source_variant_context(
    paragraph_text: List[str],
    *,
    paragraph_index: int,
    prior_candidate_paragraph_index: int,
) -> Dict[str, str]:
    """Return an exact TLC temporal/concurrent label nearest this candidate."""

    start = max(0, int(prior_candidate_paragraph_index) + 1)
    for text in reversed(paragraph_text[start:paragraph_index]):
        cleaned = _clean(text).rstrip(".")
        temporal = _TEMPORAL_VARIANT.fullmatch(cleaned)
        if temporal is not None:
            return {
                "source_variant_identity": cleaned,
                "temporal_effective_date_label": _clean(temporal.group("date")).rstrip(
                    "."
                ),
                "temporal_variant_kind": str(temporal.group("kind") or "").lower(),
                "temporal_variant_label": cleaned,
                "temporal_variant_unit": str(temporal.group("unit") or "").lower(),
            }
        as_added = _AS_ADDED_VARIANT.fullmatch(cleaned)
        if as_added is not None:
            return {
                "concurrent_variant_label": cleaned,
                "concurrent_variant_unit": str(
                    as_added.group("unit") or ""
                ).lower(),
                "source_variant_identity": cleaned,
                "source_variant_kind": "as_added",
            }
        concurrent = _CONCURRENT_VARIANT.fullmatch(cleaned)
        if concurrent is not None:
            return {
                "concurrent_variant_label": cleaned,
                "concurrent_variant_unit": str(concurrent.group("unit") or "").lower(),
                "source_variant_identity": cleaned,
            }
    return {}


def _source_heading_anchor_identity(
    paragraphs: Sequence[Any],
    *,
    paragraph_index: int,
    prior_candidate_paragraph_index: int,
    section_number: str,
    parent_article: str,
) -> str:
    """Return TLC's exact named source anchor nearest one section heading.

    The official HTML gives ordinary sections a public section anchor followed
    by a source-record anchor such as ``194829.201067``. Concurrent enactments
    can intentionally repeat the public section number, while the source-record
    anchors remain distinct. Retaining that exact source identity lets strict
    closure distinguish those official variants without relying on encounter
    order. Synthetic or changed source shapes without a distinct named anchor
    remain unlabeled and therefore continue to fail closed.
    """

    start = max(0, int(prior_candidate_paragraph_index) + 1)
    excluded = {
        _clean(section_number).casefold(),
        _clean(parent_article).casefold(),
    }
    candidates: list[str] = []
    for paragraph in paragraphs[start:paragraph_index]:
        find_all = getattr(paragraph, "find_all", None)
        if not callable(find_all):
            continue
        for anchor in find_all("a", attrs={"name": True}):
            value = _clean(str(anchor.get("name") or ""))
            if value and value.casefold() not in excluded:
                candidates.append(value)
    return candidates[-1] if candidates else ""


def parse_texas_chapter_html(
    html: str,
    *,
    code_name: str = "Penal Code",
    code_abbrev: str = "PE",
    chapter_number: str = "",
    member_name: str = "",
    source_url: str = "",
    zip_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse ``p.left`` Sec./Art. blocks from one tcss chapter HTML page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    paras = [p for p in soup.find_all("p") if "left" in (p.get("class") or [])]
    if not paras:
        return []

    chapter = chapter_number or _chapter_from_member(member_name)
    official_url = source_url or (
        chapter_html_url(code_abbrev, chapter) if chapter else STATUTE_ORIGIN
    )
    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    current_anchor = ""
    body_parts: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, current_anchor, body_parts
        if not current_number:
            return
        if _RESERVED.search(current_name or ""):
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        body = _clean(" ".join(body_parts))
        if len(body) < 40:
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_number = ""
            return
        heading = current_name or f"§ {current_number}"
        link = official_url
        if current_anchor:
            link = f"{official_url}#{current_anchor}"
        structured = {
            "source_kind": (
                "official_texas_statutes_html_zip"
                if zip_url
                else "official_texas_chapter_html"
            ),
            "source_authority_class": "official",
            "discovery_method": "tcss_p_left_sec",
            "skip_hydrate": True,
        }
        if zip_url:
            structured["zip_url"] = zip_url
        if member_name:
            structured["zip_member"] = member_name
        statutes.append(
            NormalizedStatute(
                state_code="TX",
                state_name="Texas",
                statute_id=f"{code_name} § {current_number}",
                code_name=code_name,
                chapter_number=chapter or None,
                section_number=current_number,
                section_name=heading[:200],
                full_text=body,
                source_url=link,
                official_cite=f"Tex. {code_name} § {current_number}",
                metadata=StatuteMetadata(),
                structured_data=structured,
            )
        )
        current_number = ""
        current_name = ""
        current_anchor = ""
        body_parts = []

    for para in paras:
        text = _clean(para.get_text(" "))
        if not text:
            continue
        match = _SEC_RE.match(text)
        if match:
            flush()
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if _RESERVED.search(text):
                current_number = ""
                current_name = ""
                current_anchor = ""
                body_parts = []
                continue
            current_number = match.group(2).rstrip(".")
            current_anchor = str(para.get("id") or current_number)
            title_match = _TITLE_RE.match(text)
            if title_match:
                current_name = f"§ {current_number}. {title_match.group(1).strip()}"
                rest = _clean(title_match.group(2))
            else:
                current_name = f"§ {current_number}."
                rest = _clean(_SEC_RE.sub("", text, count=1))
            if rest and not _is_history(rest) and not _RESERVED.search(current_name):
                body_parts.append(rest)
            continue
        if not current_number:
            continue
        style = str(para.get("style") or "")
        if "text-indent" not in style or _is_history(text):
            continue
        body_parts.append(text)
    flush()
    return statutes


def parse_texas_chapter_html_strict(
    html: str,
    *,
    code_name: str,
    code_abbrev: str,
    member_name: str,
    source_url: str,
    zip_url: str,
) -> Tuple[List[NormalizedStatute], Dict[str, Any]]:
    """Parse one retained ZIP member with exact candidate closure.

    The ordinary parser above intentionally preserves the historical bounded
    behavior.  This strict parser is used only by the uncapped statutory ZIP route.
    Every source heading beginning with ``Sec.`` or ``Art.`` is classified as
    an operative row, an explicit terminal disposition, or a parser residual.
    Concurrent Texas codifications are kept distinct by exact member and
    source-occurrence identities instead of being silently de-duplicated.
    """

    try:
        from bs4 import BeautifulSoup
    except (
        ImportError
    ) as exc:  # pragma: no cover - dependency is required in production
        raise RuntimeError(
            "BeautifulSoup is required for strict Texas parsing"
        ) from exc

    soup = BeautifulSoup(html or "", "html.parser")
    paragraphs = list(soup.find_all("p"))
    body_blocks = list(soup.find_all(("p", "table")))
    block_index_by_node = {id(node): index for index, node in enumerate(body_blocks)}
    paragraph_text = [_clean(node.get_text(" ")) for node in paragraphs]
    candidates: List[Tuple[int, re.Match[str]]] = []
    for index, text in enumerate(paragraph_text):
        match = _SEC_RE.match(text)
        if match is not None:
            candidates.append((index, match))

    member_token = _strict_member_token(member_name)
    member_chapter = _chapter_from_member(member_name)
    statutes: List[NormalizedStatute] = []
    terminal_dispositions: List[Dict[str, Any]] = []
    parser_residuals: List[Dict[str, Any]] = []
    source_identity_occurrences: Dict[str, int] = {}
    source_identity_rows: Dict[str, List[NormalizedStatute]] = {}
    duplicate_source_identities: List[Dict[str, Any]] = []
    active_article = ""

    for candidate_index, (paragraph_index, match) in enumerate(candidates):
        kind = str(match.group(1) or "").rstrip(".").lower()
        raw_number = str(match.group(2) or "").rstrip(".")
        heading_text = paragraph_text[paragraph_index]
        heading_tail = _clean(heading_text[match.end() :])
        prior_candidate_paragraph_index = (
            candidates[candidate_index - 1][0] if candidate_index else -1
        )
        temporal_context = _source_variant_context(
            paragraph_text,
            paragraph_index=paragraph_index,
            prior_candidate_paragraph_index=prior_candidate_paragraph_index,
        )
        next_candidate = (
            candidates[candidate_index + 1]
            if candidate_index + 1 < len(candidates)
            else None
        )
        next_paragraph_index = (
            next_candidate[0] if next_candidate is not None else len(paragraphs)
        )
        heading_node = paragraphs[paragraph_index]
        first_body_block = block_index_by_node[id(heading_node)] + 1
        next_body_block = (
            block_index_by_node[id(paragraphs[next_paragraph_index])]
            if next_paragraph_index < len(paragraphs)
            else len(body_blocks)
        )

        if kind == "art":
            active_article = raw_number
        parent_article = ""
        if (
            kind == "sec"
            and active_article
            and member_chapter
            and not raw_number.casefold().startswith(f"{member_chapter}.".casefold())
        ):
            parent_article = active_article
        source_anchor_identity = _source_heading_anchor_identity(
            paragraphs,
            paragraph_index=paragraph_index,
            prior_candidate_paragraph_index=prior_candidate_paragraph_index,
            section_number=raw_number,
            parent_article=parent_article,
        )

        anchor_node = heading_node.find("a", href=True)
        anchor_text = (
            _clean(anchor_node.get_text(" ")) if anchor_node is not None else ""
        )
        anchor_match = _SEC_RE.match(anchor_text) if anchor_text else None
        if anchor_match is not None:
            heading_tail = _clean(anchor_text[anchor_match.end() :])
            heading = heading_tail.rstrip(".")
            first_body = (
                _clean(heading_text[len(anchor_text) :])
                if heading_text.startswith(anchor_text)
                else ""
            )
        else:
            title_match = _TITLE_RE.match(heading_text)
            if title_match:
                heading = title_match.group(1).strip().rstrip(".")
                first_body = _clean(title_match.group(2))
            else:
                # Compact enactments sometimes omit a catchline entirely and
                # begin the operative sentence immediately after ``Sec. N.``.
                # The source-bound prefix still proves the candidate; retain
                # its whole tail as body instead of silently dropping it.
                heading = f"§ {raw_number}"
                first_body = heading_tail
        terminal = _exact_terminal_disposition(heading_tail)

        body_parts: List[str] = []
        if first_body and not _is_history(first_body):
            body_parts.append(first_body)
        for body_node in body_blocks[first_body_block:next_body_block]:
            body_text = _clean(body_node.get_text(" "))
            if not body_text or _is_history(body_text):
                continue
            if body_node.name == "table" or "text-indent" in str(
                body_node.get("style") or ""
            ):
                body_parts.append(body_text)
        body = _clean(" ".join(body_parts))

        if terminal:
            terminal_dispositions.append(
                {
                    "disposition": terminal,
                    "heading": heading_text,
                    "heading_kind": kind,
                    "section_number": raw_number,
                    "source_paragraph_index": paragraph_index,
                }
            )
            continue

        next_is_internal_section = False
        if kind == "art" and next_candidate is not None:
            next_match = next_candidate[1]
            next_number = str(next_match.group(2) or "").rstrip(".")
            next_is_internal_section = (
                str(next_match.group(1) or "").lower().startswith("sec")
                and bool(member_chapter)
                and not next_number.casefold().startswith(
                    f"{member_chapter}.".casefold()
                )
            )
        if next_is_internal_section and not body:
            terminal_dispositions.append(
                {
                    "disposition": "internal_section_container",
                    "heading": heading_text,
                    "heading_kind": kind,
                    "section_number": raw_number,
                    "source_paragraph_index": paragraph_index,
                }
            )
            continue
        if not body:
            parser_residuals.append(
                {
                    "heading": heading_text,
                    "heading_kind": kind,
                    "normalized_length": len(body),
                    "reason": "short_or_unparsed_section_body",
                    "section_number": raw_number,
                    "source_paragraph_index": paragraph_index,
                }
            )
            continue

        if parent_article:
            display_number = f"art. {parent_article} sec. {raw_number}"
            identity_number = f"art-{parent_article}:sec-{raw_number}"
            cite = f"Tex. {code_name} art. {parent_article}, § {raw_number}"
        elif kind == "art":
            display_number = raw_number
            identity_number = f"art-{raw_number}"
            cite = f"Tex. {code_name} art. {raw_number}"
        else:
            display_number = raw_number
            identity_number = f"sec-{raw_number}"
            cite = f"Tex. {code_name} § {raw_number}"

        identity_base = (
            f"tx:{code_abbrev.lower()}:{member_token}:{identity_number.casefold()}"
        )
        occurrence = source_identity_occurrences.get(identity_base, 0) + 1
        source_identity_occurrences[identity_base] = occurrence
        variant_label = str(temporal_context.get("source_variant_identity") or "")
        canonical_key = (
            f"{identity_base}:variant-"
            f"{hashlib.sha256(variant_label.encode('utf-8')).hexdigest()[:16]}"
            if variant_label
            else f"{identity_base}:occ-{occurrence}"
        )
        if occurrence > 1:
            duplicate_source_identities.append(
                {
                    "canonical_identity_base": identity_base,
                    "occurrence": occurrence,
                    "heading": heading_text,
                    "source_variant_identity": variant_label,
                }
            )

        anchor = raw_number
        anchor_node = heading_node.find("a", href=True)
        if anchor_node is not None:
            href = str(anchor_node.get("href") or "")
            if "#" in href and href.rsplit("#", 1)[-1]:
                anchor = href.rsplit("#", 1)[-1]
        row_source_url = f"{source_url.rsplit('#', 1)[0]}#{anchor}"
        statute_id = f"{code_name} ({member_token}) § {display_number}"
        if temporal_context.get("temporal_variant_label"):
            statute_id = (
                f"{statute_id} [{temporal_context['temporal_variant_kind']} "
                f"{temporal_context['temporal_effective_date_label']}]"
            )
        elif temporal_context.get("concurrent_variant_label"):
            concurrent_identity = str(
                temporal_context.get("source_variant_identity") or ""
            )
            concurrent_token = hashlib.sha256(
                concurrent_identity.encode("utf-8")
            ).hexdigest()[:16]
            statute_id = (
                f"{statute_id} [concurrent source variant {concurrent_token}]"
            )
        elif occurrence > 1:
            statute_id = f"{statute_id} [source occurrence {occurrence}]"

        statute = NormalizedStatute(
            state_code="TX",
            state_name="Texas",
            statute_id=statute_id,
            code_name=code_name,
            chapter_number=member_chapter or None,
            section_number=display_number,
            section_name=(heading or f"§ {display_number}")[:200],
            full_text=body,
            source_url=row_source_url,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "canonical_section_key": canonical_key,
                "code_abbrev": code_abbrev,
                "discovery_method": "strict_tcss_zip_member_heading_frontier",
                "heading_kind": kind,
                "parent_article": parent_article,
                "skip_hydrate": True,
                "source_authority_class": "official",
                "source_anchor_identity": source_anchor_identity,
                "source_kind": "official_texas_statutes_html_zip",
                "source_occurrence": occurrence,
                "strict_source_closure": True,
                **temporal_context,
                "zip_member": member_name,
                "zip_url": zip_url,
            },
        )
        statutes.append(statute)
        source_identity_rows.setdefault(identity_base, []).append(statute)

    ambiguous_statute_ids: set[int] = set()
    for identity_base, identity_rows in source_identity_rows.items():
        if len(identity_rows) < 2:
            continue
        labels = [
            str((row.structured_data or {}).get("source_variant_identity") or "")
            for row in identity_rows
        ]
        unlabeled = [
            row for row, label in zip(identity_rows, labels, strict=True) if not label
        ]
        explicit_labels = [label for label in labels if label]
        has_concurrent_context = any(
            bool((row.structured_data or {}).get("concurrent_variant_label"))
            for row in identity_rows
        )
        if (
            len(unlabeled) == 1
            and has_concurrent_context
            and len(explicit_labels) == len(set(explicit_labels))
        ):
            primary = unlabeled[0]
            primary_label = "primary_unlabeled_concurrent_source_occurrence"
            primary_structure = dict(primary.structured_data or {})
            primary_structure.update(
                {
                    "canonical_section_key": (
                        f"{identity_base}:variant-"
                        f"{hashlib.sha256(primary_label.encode('utf-8')).hexdigest()[:16]}"
                    ),
                    "concurrent_variant_role": primary_label,
                    "source_variant_identity": primary_label,
                }
            )
            primary.structured_data = primary_structure
            primary.statute_id = (
                f"{primary.statute_id} [primary concurrent source occurrence]"
            )
            labels = [
                str((row.structured_data or {}).get("source_variant_identity") or "")
                for row in identity_rows
            ]
        if all(labels) and len(labels) == len(set(labels)):
            continue
        source_anchors = [
            str((row.structured_data or {}).get("source_anchor_identity") or "")
            for row in identity_rows
        ]
        if all(source_anchors) and len(source_anchors) == len(set(source_anchors)):
            for row, prior_label, source_anchor in zip(
                identity_rows,
                labels,
                source_anchors,
                strict=True,
            ):
                exact_label = f"tlc-source-anchor:{source_anchor}"
                if prior_label:
                    exact_label = f"{prior_label} | {exact_label}"
                structure = dict(row.structured_data or {})
                structure.update(
                    {
                        "canonical_section_key": (
                            f"{identity_base}:variant-"
                            f"{hashlib.sha256(exact_label.encode('utf-8')).hexdigest()[:16]}"
                        ),
                        "source_variant_disambiguation": (
                            "official_tlc_named_source_anchor"
                        ),
                        "source_variant_identity": exact_label,
                    }
                )
                row.structured_data = structure
                row.statute_id = (
                    f"{row.statute_id} [official source anchor {source_anchor}]"
                )
            labels = [
                str((row.structured_data or {}).get("source_variant_identity") or "")
                for row in identity_rows
            ]
        if all(labels) and len(labels) == len(set(labels)):
            continue
        for row in identity_rows:
            ambiguous_statute_ids.add(id(row))
            parser_residuals.append(
                {
                    "canonical_identity_base": identity_base,
                    "heading": str(row.section_name or ""),
                    "heading_kind": str(
                        (row.structured_data or {}).get("heading_kind") or ""
                    ),
                    "reason": "ambiguous_unlabeled_or_repeated_source_variant",
                    "section_number": str(row.section_number or ""),
                    "source_variant_identity": str(
                        (row.structured_data or {}).get("source_variant_identity") or ""
                    ),
                }
            )
    if ambiguous_statute_ids:
        statutes = [row for row in statutes if id(row) not in ambiguous_statute_ids]

    report: Dict[str, Any] = {
        "candidate_sections": len(candidates),
        "closed": (
            len(candidates)
            == len(statutes) + len(terminal_dispositions) + len(parser_residuals)
            and not parser_residuals
        ),
        "duplicate_source_identities": duplicate_source_identities,
        "member_name": member_name,
        "operative_sections": len(statutes),
        "parser_residuals": parser_residuals,
        "terminal_dispositions": terminal_dispositions,
        "terminal_sections": len(terminal_dispositions),
    }
    return statutes, report


def _chapter_from_member(member_name: str) -> str:
    match = re.match(
        r"^[^.]+\.(?P<chapter>[0-9A-Za-z_-]+(?:\.[0-9A-Za-z_-]+)*?)"
        r"(?:\.v[0-9]+)?\.html?$",
        str(member_name or "").strip(),
        re.IGNORECASE,
    )
    return match.group("chapter") if match else ""


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("TEXAS_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_statute_array_path() -> Optional[Path]:
    raw = str(os.environ.get("TEXAS_STATUTE_ARRAY_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_statute_array(*, code: str = "") -> List[Tuple[str, str, str]]:
    """Local GetStatuteArray dump. Does not call the tcss API."""

    path = configured_statute_array_path()
    if path is None:
        return []
    token = (
        str(code or os.environ.get("TEXAS_STATUTE_ARRAY_CODE") or "PE").strip().upper()
    )
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return chapters_from_statute_array(payload, code=token)
