"""Project the 5-column American municipal frame into legal-record/v1.

The ordinance body lives in ``html``. This projector stores the plain text of
that body and reads a title, chapter, article, division, part, or section
number from the plain title. A section inherits the headings still in force.
Raw HTML is not a column and is not the stored text.

Jurisdiction is the place's state, ``US-OH`` for an Ohio city. A row with no
place metadata stays unset. It is not stamped ``US``, and it does not follow
the caller. The file stem is the GNIS id from the municipal seed, and that
seed place wins over a title guess. A title or the page's own canonical URL
is used only when the stem is not in the seed. A citation link to another
code is not that page. The scrape clock is not a publication date. Language
``en`` is this corpus's default for a known US state; the source file does
not label it.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import unquote, urlsplit

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    BLUEBOOK_STATE,
    STATE_NAME,
    _code_kind,
    adoption_line_dates,
    extract_history_notes,
    extract_title_num,
    format_bluebook,
    passage_dates,
    source_url_from_html,
    strip_tags,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import blank_record
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    null_text,
    sha256_text,
    strip_markup,
)

NORMALIZER_VERSION = "american-municipal-html/v4+legal-record/v1"

_BLOCK_TAG = re.compile(
    r"(?i)<\s*/?\s*(?:p|div|br|li|h[1-6]|tr|section|article)\b[^>]*>"
)
_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_TAG_REMNANT = re.compile(r"<\s*/?\s*[A-Za-z!]")
_TITLE_HEADING = re.compile(r"(?i)^\s*title\s+([0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)")
_CHAPTER_HEADING = re.compile(
    r"(?i)^\s*chapter\s+([0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)"
)
_PART_HEADING = re.compile(r"(?i)^\s*part\s+([IVXLCDM]+|\d+)\b")
_ARTICLE_HEADING = re.compile(r"(?i)^\s*article\s+([IVXLCDM]+|\d+(?:[.\-]\d+)*)")
# "Division 2" and "Division A" are headings. "Division of Fire" is a name.
_DIVISION_HEADING = re.compile(
    r"(?i)^\s*division\s+([0-9]+(?:[.\-][0-9]+)*|[IVXLCDM]+|[A-Z])\b"
)
_HEADING_PATTERNS = (
    ("title", _TITLE_HEADING),
    ("chapter", _CHAPTER_HEADING),
    ("article", _ARTICLE_HEADING),
    ("division", _DIVISION_HEADING),
    ("part", _PART_HEADING),
)
_HEADING_LABELS = {
    "title": "Title",
    "chapter": "Chapter",
    "article": "Article",
    "division": "Division",
    "part": "Part",
}
_HISTORY_CAP = 12
_NOTE_CAP = 500
HeadingStack = tuple[tuple[str, str], ...]
_STATE_NAMES_LONGEST = sorted(STATE_NAME.values(), key=len, reverse=True)
# A possessive ("Iowa's") is not the state. The longest name is tried first,
# so "West Virginia" wins over "Virginia".
_STATE_NAME_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(name) for name in _STATE_NAMES_LONGEST) + r")\b(?!')"
)
# A postal code counts after a comma or inside parentheses, so "IN_THE" is not Indiana.
_STATE_CODE_RE = re.compile(r"(?:,\s*|\()([A-Z]{2})\)?(?!\w)")
_NAME_TO_CODE = {name.casefold(): code for code, name in STATE_NAME.items()}
_EMBEDDED_STATE_RE = re.compile(
    r"(?i)\b(city|town|village|borough|county)\s+of\s+("
    + "|".join(re.escape(name) for name in _STATE_NAMES_LONGEST)
    + r")\s+([A-Za-z][A-Za-z0-9.'’\-]*(?:\s+[A-Za-z][A-Za-z0-9.'’\-]+){0,3})"
)
_MUNICIPAL_RE = re.compile(
    r"(?i)\b(city|town|village|borough|county)\s+of\s+"
    r"([A-Z][A-Za-z0-9.'’\-]*(?:\s+[A-Z][A-Za-z0-9.'’\-]*){0,5})"
)
_SMALL_WORDS = frozenset({"of", "the", "and", "de", "la", "le", "du", "to"})
_GENERIC_CORES = frozenset({
    "code",
    "codes",
    "ordinance",
    "ordinances",
    "municipal",
    "home",
    "document",
    "state",
    "charter",
    "city",
    "town",
    "village",
    "borough",
    "county",
    "one",
    "welcome",
    "official",
    "website",
    "news",
    "page",
    "chamber",
    "commerce",
    "west",
    "east",
    "north",
    "south",
})
_CHAMBER_SUFFIX = re.compile(r"(?i)\s+chamber\s+of\s+commerce\s*$")
# "Utah State Criminal Code" cites a state code. It is not a city in Utah.
_TAIL_REJECT = re.compile(
    r"(?i)^\s*(?:state|code|codes|criminal|statute|statutes|chapter|section)\b"
)
# "West Pennsylvania Avenue" is a street. It is not a city in Pennsylvania.
_STREET_TAIL = re.compile(
    r"(?i)^\s+(?:avenue|ave|street|st|road|rd|boulevard|blvd|drive|dr|lane|ln|highway|hwy|parkway|pkwy|way|place|court|ct)\b"
)
_PLSS_TITLE = re.compile(r"(?i)\b(?:township|range)\b")
_PREFIX_DISPLAY = {
    "city": "City of",
    "town": "Town of",
    "village": "Village of",
    "borough": "Borough of",
    "county": "County of",
}
# The page URL is the scrape origin. Stylesheets and citation hosts are not.
_CHROME_HOST_SUFFIXES = (
    "amazonaws.com",
    "w3.org",
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "facebook.com",
    "schema.org",
    "wordpress.org",
    "wp.com",
    "parastorage.com",
    "googletagmanager.com",
    "gmpg.org",
    "yoast.com",
    "ogp.me",
    "doubleclick.net",
    "cloudflare.com",
)
_ORIGIN_URL_RES = (
    re.compile(
        r"(?i)<link\b[^>]*\brel\s*=\s*[\"']canonical[\"'][^>]*\bhref\s*=\s*[\"']([^\"']+)"
    ),
    re.compile(
        r"(?i)<link\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"'][^>]*\brel\s*=\s*[\"']canonical[\"']"
    ),
    re.compile(
        r"(?i)<meta\b[^>]*(?:property|name)\s*=\s*[\"']og:url[\"'][^>]*\bcontent\s*=\s*[\"']([^\"']+)"
    ),
    re.compile(
        r"(?i)<meta\b[^>]*\bcontent\s*=\s*[\"']([^\"']+)[\"'][^>]*(?:property|name)\s*=\s*[\"']og:url[\"']"
    ),
    re.compile(r"(?i)<base\b[^>]*\bhref\s*=\s*[\"']([^\"']+)"),
)
_STATUTE_SLUGS = frozenset({
    "rcw", "wac", "ors", "usc", "cfr", "ksa", "aca", "crs", "mrs", "nrs",
    "ars", "hrs", "mcl", "occ", "osc",
})
_HOST_LABEL_SKIP = frozenset({"www", "www2", "ci", "city", "mail", "web"})
_STATE_HOST_NAMES = tuple(
    sorted(
        (
            (re.sub(r"[^a-z]", "", name.casefold()), code)
            for code, name in STATE_NAME.items()
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def project_american_municipal_row(
    row: Mapping[str, object],
    *,
    source_repo: str,
    source_revision: str,
    place_name: str | None = None,
    state_code: str | None = None,
    chapter_num: str | None = None,
    heading_stack: HeadingStack | None = None,
) -> dict[str, object]:
    record = blank_record()
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    title = strip_markup(row.get("html_title"))
    text = plain_law_text(row.get("html"))
    notes, passage = _history(row.get("html"))
    effective = max(passage) if passage else None
    section = extract_title_num(title or "")
    record.update(
        {
            "admin_level": "us-municipal",
            "instrument_type": "ordinance",
            "title": title,
            "text": text,
            "published_date": None,
            "effective_date": effective,
            "content_sha256": sha256_text(text),
            "normalizer_version": NORMALIZER_VERSION,
            "source_repo": source_repo,
            "source_revision": source_revision,
            "entry_cid": null_text(row.get("cid")),
            "source_url": source_url_from_html(
                row.get("html") if isinstance(row.get("html"), str) else ""
            ),
        }
    )
    _stamp_place(record, place_name=place_name, state_code=state_code, section=section, effective=effective)
    provenance["content_complete"] = text is not None
    provenance["source_policy"] = None
    provenance["source_official"] = None
    provenance["doc_id"] = row.get("doc_id")
    provenance["doc_order"] = row.get("doc_order")
    if notes:
        provenance["history_notes"] = [note[:_NOTE_CAP] for note in notes[:_HISTORY_CAP]]
    if passage:
        provenance["passage_dates"] = passage[:_HISTORY_CAP]
    incoming: HeadingStack = heading_stack or ()
    if not incoming and chapter_num:
        incoming = (("chapter", chapter_num),)
    _stamp_heading(
        provenance,
        title,
        section=section,
        stack=heading_after(title, incoming),
    )
    if "html" in record or (isinstance(text, str) and _TAG_REMNANT.search(text)):
        raise RuntimeError("html must not be copied into a legal record")
    return record


def heading_after(title: str | None, stack: HeadingStack) -> HeadingStack:
    """Headings in force after this plain chunk title.

    The stack follows document order. A heading of a kind already on the
    stack replaces that kind and drops every heading that followed it, so a
    new chapter clears the article and part that belonged to the previous
    chapter. A kind that is not on the stack is appended. A section title
    does not change the stack. ``CHAPTER 180`` later in a section title is
    not a heading.
    """

    found = _match_heading(title)
    if found is None:
        return stack
    kind, number = found
    kept: list[tuple[str, str]] = []
    for item in stack:
        if item[0] == kind:
            break
        kept.append(item)
    kept.append((kind, number))
    return tuple(kept)


def chapter_after(title: str | None, current: str | None) -> str | None:
    """Chapter number in force after this plain chunk title."""

    incoming: HeadingStack = (("chapter", current),) if current else ()
    for kind, number in heading_after(title, incoming):
        if kind == "chapter":
            return number
    return None


def place_from_titles(titles: Sequence[str | None]) -> tuple[str, str] | None:
    """Return ``(place, state_code)`` when the titles name exactly one pair.

    A city with no state stays unset. Two cities, two states, or two
    municipal prefixes for one name stay unset. Nothing is filled from a
    city name alone.
    """

    texts = [title.strip() for title in titles if isinstance(title, str) and title.strip()]
    mentions: list[tuple[str, str, str, str]] = []
    for text in texts:
        # A range-and-township line names a survey corner, not the city.
        if _PLSS_TITLE.search(text) and re.search(r"(?i)\bcounty\b", text):
            continue
        consumed = _embedded_state_mentions(text, mentions)
        for start, end, code, kind in _state_spans(text):
            if any(start >= left and end <= right for left, right in consumed):
                continue
            raw_before = text[:start]
            found = _place_before(raw_before)
            if found is None:
                continue
            prefix, core = found
            # "City of Wyoming" is not the state of Wyoming. A postal code can
            # still say which state that city is in.
            if kind == "name" and core.casefold() == STATE_NAME[code].casefold():
                continue
            if kind == "name" and _STREET_TAIL.match(text[end:]) is not None:
                continue
            # A multi-word name needs a comma or a municipal prefix. That keeps
            # "St. Croix Falls, Wisconsin" and rejects "Parking Along Virginia".
            comma = raw_before.rstrip().endswith(",")
            if not prefix and not comma and len(core.split()) != 1:
                continue
            if (
                kind == "name"
                and not prefix
                and not comma
                and _TAIL_REJECT.match(text[end:]) is not None
            ):
                continue
            mentions.append((core.casefold(), code, prefix, core))
    pairs = {(core, code) for core, code, _prefix, _display in mentions}
    if len(pairs) != 1:
        return None
    core_fold, code = next(iter(pairs))
    display = ""
    prefixes = {prefix for fold, _code, prefix, _display in mentions if fold == core_fold and prefix}
    for title in texts:
        for match in _MUNICIPAL_RE.finditer(title):
            other = _clean_core(match.group(2))
            if other is not None and other.casefold() == core_fold:
                prefixes.add(match.group(1).casefold())
    if len(prefixes) > 1:
        return None
    for fold, _code, _prefix, core in mentions:
        if fold != core_fold:
            continue
        display = _prefer_display(display, core)
    if not display:
        return None
    prefix = next(iter(prefixes)) if prefixes else ""
    place = f"{_PREFIX_DISPLAY[prefix]} {display}" if prefix else display
    return place, code


def origin_urls_from_html(value: object) -> list[str]:
    """Canonical, Open Graph, and base URLs from one HTML chunk."""

    blob = value if isinstance(value, str) else ""
    found: list[str] = []
    for pattern in _ORIGIN_URL_RES:
        for match in pattern.finditer(blob):
            url = html.unescape(match.group(1)).strip().split("#", 1)[0]
            if url.startswith(("http://", "https://")) and url not in found:
                found.append(url)
    return found


def place_from_origin_urls(urls: Sequence[str | None]) -> tuple[str, str] | None:
    """One municipality from the file's own page URLs, or nothing.

    The state has to be written in that URL. A hostname with no state, and a
    link to some other state's code, do not fill the place.
    """

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        found = _place_from_origin_url(url)
        if found is None:
            continue
        key = (found[0].casefold(), found[1])
        if key in seen:
            continue
        seen.add(key)
        pairs.append(found)
    if len(pairs) != 1:
        return None
    return pairs[0]


def _gnis_seed_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "municipal"
        / "seeds"
        / "americas"
        / "US.jsonl"
    )


@lru_cache(maxsize=1)
def gnis_place_index() -> dict[str, tuple[str, str]]:
    """Primary GNIS id to ``(place, state_code)`` from the municipal seed."""

    path = _gnis_seed_path()
    index: dict[str, tuple[str, str]] = {}
    if not path.is_file():
        return index
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        gnis = str(row.get("gnis") or "").strip()
        place = str(row.get("name") or "").strip()
        state = str(row.get("state_code") or "").strip().upper()
        if gnis and place and state in STATE_NAME:
            index[gnis] = (place, state)
    return index


def place_from_gnis(
    gnis: str | None,
    index: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[str, str] | None:
    """Place assigned to this file by the scraper seed, or nothing.

    Alternate GNIS ids are not consulted. One id is shared by more than one
    place in the alternate list.
    """

    key = str(gnis or "").strip()
    if not key:
        return None
    table = gnis_place_index() if index is None else index
    found = table.get(key)
    if found is None:
        return None
    place, state = found
    if not place or state not in STATE_NAME:
        return None
    return place, state


def resolve_place(
    place_name: str | None,
    state_code: str | None,
    titles: Sequence[str | None],
    urls: Sequence[str | None] = (),
    gnis: str | None = None,
) -> tuple[str | None, str | None]:
    """Keep metadata. The seed fills a file that has neither field."""

    place = (place_name or "").strip()
    state = (state_code or "").strip()
    if place or _known_state(state):
        return (place or None), (state or None)
    found = place_from_gnis(gnis)
    if found is not None:
        return found
    found = place_from_titles(titles)
    if found is not None:
        return found
    found = place_from_origin_urls(urls)
    if found is None:
        return None, None
    return found


def plain_law_text(value: object) -> str | None:
    """Drop tags and keep the ordinance words, including a bare less-than sign."""

    raw = null_text(value)
    if raw is None:
        return None
    blocked = _BLOCK_TAG.sub("\n", raw)
    cleaned = html.unescape(_TAG.sub("", blocked))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned or _TAG_REMNANT.search(cleaned):
        return None
    return cleaned


def _history(value: object) -> tuple[list[str], list[str]]:
    raw = value if isinstance(value, str) else ""
    if not raw.strip():
        return [], []
    notes = extract_history_notes(raw)
    dates: list[str] = []
    for note in notes:
        for _token, iso in passage_dates(note):
            if iso not in dates:
                dates.append(iso)
    # A title page states "Adopted: October 16, 1990" outside any history note.
    # Notes that already have a date keep it; a "current through" stamp does not.
    if not dates:
        for _token, iso in adoption_line_dates(strip_tags(raw)):
            if iso not in dates:
                dates.append(iso)
    return notes, dates


def _chrome_host(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in _CHROME_HOST_SUFFIXES)


def _words_from_slug(slug: str) -> str | None:
    words = [word for word in re.split(r"[-_]+", slug) if word]
    if not words:
        return None
    display = " ".join(word[:1].upper() + word[1:] for word in words)
    if display.casefold() in _GENERIC_CORES:
        return None
    return display


def _city_from_host_rest(rest: str) -> str | None:
    text = rest.strip("-_")
    prefix = ""
    match = re.fullmatch(r"(city|town|village|borough|county)of(.+)", text)
    if match:
        prefix = match.group(1)
        text = match.group(2).strip("-_")
    if len(text) < 3 or text in _GENERIC_CORES:
        return None
    display = _words_from_slug(text)
    if display is None:
        return None
    if prefix:
        return f"{_PREFIX_DISPLAY[prefix]} {display}"
    return display


def _place_from_sld(sld: str) -> tuple[str, str] | None:
    text = sld.casefold()
    for name, code in _STATE_HOST_NAMES:
        if text.endswith(name) and len(text) > len(name):
            city = _city_from_host_rest(text[: -len(name)])
            if city:
                return city, code
    match = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)-([a-z]{2})", text)
    if match and match.group(2).upper() in STATE_NAME:
        city = _city_from_host_rest(match.group(1))
        if city:
            return city, match.group(2).upper()
    # A glued postal code is not a state token. cityoftacoma.org,
    # cityofarkadelphia.com, and cityofbolivar.com end in ma, ia, and ar
    # because those letters finish the city name.
    return None


def _place_from_publisher_path(host: str, path: str) -> tuple[str, str] | None:
    parts = [unquote(part) for part in path.split("/") if part]
    if host.endswith("codepublishing.com") and len(parts) >= 2:
        code = parts[0].upper()
        if code in STATE_NAME and parts[1].casefold() not in _STATUTE_SLUGS:
            city = _words_from_slug(parts[1])
            if city:
                return city, code
    if host.endswith("library.municode.com") and len(parts) >= 2:
        code = parts[0].upper()
        slug = parts[1].casefold()
        if code in STATE_NAME and slug not in _STATUTE_SLUGS and slug != "codes":
            city = _words_from_slug(parts[1])
            if city:
                return city, code
    if host.endswith("municipal.codes") and len(parts) >= 2:
        code = parts[0].upper()
        raw_slug = parts[1]
        slug = raw_slug.casefold()
        # Check the original segment. Casefold would make "RCW".isupper() false.
        if (
            code in STATE_NAME
            and slug not in _STATUTE_SLUGS
            and not raw_slug.isupper()
            and len(slug) > 3
        ):
            city = _words_from_slug(raw_slug)
            if city:
                return city, code
    if host.endswith("amlegal.com"):
        for index, part in enumerate(parts[:-1]):
            if part.casefold() == "codes":
                return _place_from_sld(parts[index + 1])
    if host.endswith("encodeplus.com"):
        for part in parts:
            # littleton-co-cc. A looser "{word}-or-{word}" would read Oregon.
            match = re.fullmatch(
                r"([a-z0-9]{3,})-([a-z]{2})-([a-z0-9]{1,4})",
                part.casefold(),
            )
            if match and match.group(2).upper() in STATE_NAME:
                city = _words_from_slug(match.group(1))
                if city:
                    return city, match.group(2).upper()
    return None


def _place_from_origin_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or _chrome_host(host):
        return None
    found = _place_from_publisher_path(host, unquote(parsed.path or ""))
    if found is not None:
        return found
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2:] == ["gov", "pr"] and "PR" in STATE_NAME:
        city = _words_from_slug(labels[-3])
        if city and labels[-3] not in _HOST_LABEL_SKIP:
            return city, "PR"
    # agency.dc.gov names a DC office, not a municipality.
    if (
        len(labels) >= 3
        and labels[-1] in {"gov", "us"}
        and labels[-2].upper() in STATE_NAME
        and labels[-2].upper() != "DC"
    ):
        city_label = labels[-3]
        if city_label in _HOST_LABEL_SKIP and len(labels) >= 4:
            city_label = labels[-4]
        if city_label not in _HOST_LABEL_SKIP:
            city = _words_from_slug(city_label)
            if city:
                return city, labels[-2].upper()
    if labels[0] == "www" and len(labels) > 2:
        labels = labels[1:]
    return _place_from_sld(labels[0])


def _known_state(state_code: str | None) -> str | None:
    code = (state_code or "").strip().upper()
    if code in STATE_NAME:
        return code
    return None


def _stamp_place(
    record: dict[str, object],
    *,
    place_name: str | None,
    state_code: str | None,
    section: str,
    effective: str | None,
) -> None:
    place = (place_name or "").strip()
    code = _known_state(state_code)
    record["authority"] = place or None
    record["jurisdiction"] = f"US-{code}" if code else None
    # The metadata JSON has no language field. English is the default only
    # for a state this corpus actually names.
    record["language"] = "en" if code else None
    if not place or code is None:
        return
    year = effective[:4] if effective else ""
    cite = format_bluebook(place, BLUEBOOK_STATE[code], section, year, _code_kind(place))
    record["citation"] = cite
    record["bluebook_citation"] = cite


def _match_heading(title: str | None) -> tuple[str, str] | None:
    if not title:
        return None
    for kind, pattern in _HEADING_PATTERNS:
        match = pattern.match(title)
        if match:
            return kind, match.group(1)
    return None


def _stamp_heading(
    provenance: dict[str, object],
    title: str | None,
    *,
    section: str,
    stack: HeadingStack,
) -> None:
    parts: list[str] = []
    for kind, number in stack:
        label = _HEADING_LABELS.get(kind)
        if label is None or not number:
            continue
        provenance[kind] = number
        parts.append(f"{label} {number}")
    own = _match_heading(title)
    if section:
        provenance["section"] = section
        parts.append("Section " + section)
    elif own is not None and own[0] == "article":
        # The article number stays on ``article``. ``statute`` keeps the old
        # contract for an article heading that is not itself a section.
        # A cited section must not copy that number into ``statute``: expand
        # replaces ``statute`` with the bluebook citation.
        provenance["statute"] = own[1]
    if parts:
        provenance["hierarchy_path"] = " / ".join(parts)


def _state_spans(text: str) -> list[tuple[int, int, str, str]]:
    found: list[tuple[int, int, str, str]] = []
    for match in _STATE_NAME_RE.finditer(text):
        code = _NAME_TO_CODE.get(match.group(1).casefold())
        if code:
            found.append((match.start(1), match.end(1), code, "name"))
    for match in _STATE_CODE_RE.finditer(text):
        code = match.group(1)
        if code in STATE_NAME:
            found.append((match.start(1), match.end(1), code, "code"))
    found.sort(key=lambda item: (item[0], item[0] - item[1]))
    kept: list[tuple[int, int, str, str]] = []
    for start, end, code, kind in found:
        if any(start >= left and end <= right for left, right, _code, _kind in kept):
            continue
        kept = [
            item
            for item in kept
            if not (item[0] >= start and item[1] <= end)
        ]
        kept.append((start, end, code, kind))
    kept.sort()
    return kept


def _embedded_state_mentions(
    text: str,
    mentions: list[tuple[str, str, str, str]],
) -> list[tuple[int, int]]:
    """'City of Wisconsin Dells' names Wisconsin. 'Kansas City' does not.

    The extra word has to be part of the municipality. A bare 'City of Kansas
    City' is not evidence that the state is Kansas.
    """

    consumed: list[tuple[int, int]] = []
    for match in _EMBEDDED_STATE_RE.finditer(text):
        extra = re.split(r"[,|()]", match.group(3))[0].strip()
        if not extra or extra.casefold() in _GENERIC_CORES:
            continue
        code = _NAME_TO_CODE.get(match.group(2).casefold())
        if code is None:
            continue
        # Keep the source spelling. "Wisconsin dells" is lowercase in the scrape.
        core = re.sub(r"\s+", " ", f"{match.group(2)} {extra}").strip()
        if _rejected_core(core, prefixed=True):
            continue
        mentions.append((core.casefold(), code, match.group(1).casefold(), core))
        consumed.append((match.start(2), match.end(2)))
    return consumed


def _place_before(before: str) -> tuple[str, str] | None:
    text = before.rstrip(" \t,;:(")
    if not text:
        return None
    segment = re.split(r"\s*[|\-–—]\s*", text)[-1].strip()
    segment = _CHAMBER_SUFFIX.sub("", segment).strip(" \t,.;:-(")
    if not segment:
        return None
    municipal = list(_MUNICIPAL_RE.finditer(segment))
    if municipal:
        last = municipal[-1]
        tail = re.sub(
            r"(?i)^,?\s*[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*)?\s+county\s*$",
            "",
            segment[last.end() :],
        )
        if tail.strip(" \t,.;:(") == "":
            core = _clean_core(last.group(2))
            if core is not None and not _rejected_core(core, prefixed=True):
                return last.group(1).casefold(), core
    core = _trailing_core(segment)
    if core is not None and not _rejected_core(core, prefixed=False):
        return "", core
    return None


def _trailing_core(segment: str) -> str | None:
    """The proper name at the end of a title segment, not the sentence before it."""

    kept: list[str] = []
    for word in reversed(segment.split()):
        bare = word.strip(" \t,;:|")
        if not bare:
            continue
        if bare.casefold() in _SMALL_WORDS or re.fullmatch(r"[A-Z][A-Za-z0-9.'’\-]*\.?", bare) is None:
            if kept:
                break
            continue
        kept.append(bare)
        if len(kept) == 4:
            break
    if not kept:
        return None
    kept.reverse()
    return _clean_core(" ".join(kept))


def _clean_core(raw: str) -> str | None:
    text = re.sub(r"\s+", " ", raw).strip(" \t,.;:|")
    if not text or len(text) > 60:
        return None
    words = text.split(" ")
    if len(words) > 6:
        return None
    significant = 0
    for word in words:
        if word.casefold() in _SMALL_WORDS:
            continue
        if re.fullmatch(r"[A-Z][A-Za-z0-9.'’\-]*\.?", word) is None:
            return None
        significant += 1
    if significant < 1:
        return None
    while words and words[-1].casefold() in _SMALL_WORDS:
        words.pop()
    if not words:
        return None
    core = " ".join(words)
    if len(re.sub(r"[^A-Za-z]", "", core)) < 3:
        return None
    return core


def _rejected_core(core: str, *, prefixed: bool) -> bool:
    fold = core.casefold()
    if fold in _GENERIC_CORES:
        return True
    if not prefixed and fold in _NAME_TO_CODE:
        return True
    return False


def _prefer_display(current: str, new: str) -> str:
    if current and any(char.islower() for char in current) and any(char.isupper() for char in current):
        return current
    if any(char.islower() for char in new):
        return new
    return current or new
