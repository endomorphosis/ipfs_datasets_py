"""Assign a structural heading from context the scrape already recorded.

An atom can lack a title, chapter, part, article, or section even though the
source row named that provision, the record title starts with it, or the
source URL contains it. This module fills only those empty locators. It does
not rewrite statute text, does not invent a provision number, and does not
treat a website, a collector, or a bare citation as a section.

Three results are possible. ``structural`` means a real heading number was
found. ``instrument_only`` means the law's name is known and no provision
number was found, so the atom stays without a locator. ``unresolved`` means
neither was found. A site name is stored beside either result and never
becomes the number.

An article number is also stored as the section locator. That is the same
number ``admit._with_leading_heading`` already copies, so a query by section
still finds the article. A source hierarchy or an explicit section, chapter,
part, or title field wins over a title that names a different number. A bare
citation is used only as the instrument name when it reads as one, never as
the provision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

_LOCATOR_ORDER = ("title", "chapter", "part", "article", "section")
_PROVISION = frozenset({"article", "section"})
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_ROMAN = re.compile(r"^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
_YEAR = re.compile(r"^(?:1[89][0-9]{2}|20[0-9]{2})$")
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
_LABEL = (
    r"มาตรา|§+|articles?|artikels?|articolos?|art[ií]culos?|artigos?|arts?\.?|"
    r"sections?|secs?\.?|neni|član|clan|madde|pasal|abschnitte?|paragrafs?|"
    r"paragraphs?|secciones?|sekcja"
)
_CONTAINER = (
    r"titles?|titres?|t[ií]tulos?|chapters?|chapitres?|cap[ií]tulos?|kapitels?|"
    r"parts?|parties|teils?"
)
_NUMBER = r"[0-9]{1,5}(?:\.[0-9]{1,4})?[A-Za-z]{0,3}|[IVXLCDM]{1,8}"
_SUFFIX = re.compile(
    rf"(?i)^(?P<name>.+?)\s+[-–—]\s*(?P<kind>{_LABEL})\s*(?P<num>{_NUMBER})\s*$"
)
_LEADING = re.compile(rf"(?i)^(?P<kind>{_LABEL})\s*(?P<num>{_NUMBER})\b")
_CONTAINER_LINE = re.compile(
    rf"(?i)^(?P<kind>{_CONTAINER})\s+(?P<num>{_NUMBER}|[A-Za-z]+)\b"
)
_TRAILING_CONTAINER = re.compile(
    rf"(?i)(?:,\s*|\s+)(?P<kind>{_CONTAINER})\s+(?P<num>{_NUMBER}|[A-Za-z]+)\s*$"
)
_DUPLICATE = re.compile(
    r"^([0-9]{1,4}(?:\.[0-9]{1,4})?[A-Za-z]{0,3})\s+\1(?:\s|[.)])"
)
_DOTTED = re.compile(r"^([0-9]{1,4}[A-Za-z]{0,3})\s*[.)]\s+\S")
_MARGINAL = re.compile(r"^\*?([0-9]{1,5}(?:\.[0-9]{1,6})?[A-Za-z]{0,3})\s+\S")
_LEADING_WORD = re.compile(
    rf"(?i)^(?P<kind>{_LABEL})\s+(?P<num>[A-Za-z]+(?:[-\s]+[A-Za-z]+)?)\b"
)
_ANNEX = re.compile(
    r"(?i)^(?P<kind>articles?|art\.?|sections?|sec\.?|§+)?\s*"
    r"(?P<label>annexe?s?|appendices|appendix|schedules?|anlagen?|anh[aä]nge?|"
    r"anexos?|bijlagen?)"
    r"(?:\s+(?P<extra>[0-9]{1,4}|[IVXLCDM]{1,8}))?\s*$"
)
_TAILED = re.compile(
    r"(?i)^(?P<name>.+?)\s+[-–—]\s*(?P<rest>"
    r"(?:(?:art\.?|articles?|§+|abschnitte?|anl\.?|anlagen?|anh[aä]nge?|annexe?s?)"
    r"\s*[0-9]{1,5}[A-Za-z]{0,3}\s*)+)$"
)
_TAIL_PIECE = re.compile(
    r"(?i)(?P<kind>art\.?|articles?|§+|abschnitte?|anl\.?|anlagen?|anh[aä]nge?|annexe?s?)"
    r"\s*(?P<num>[0-9]{1,5}[A-Za-z]{0,3})"
)
_EMBEDDED_CONTAINER = re.compile(
    rf"(?i)\b(?P<kind>{_CONTAINER})\s+(?P<num>{_NUMBER}|[A-Za-z]+)\b"
)
_BARE = re.compile(rf"(?i)^({_NUMBER})\s*[.)]?\s*$")
_FIELD = re.compile(rf"(?i)^(?P<kind>{_LABEL}|paragraphs?|paragrafs?)?\s*(?P<num>{_NUMBER})\.?$")
_PATH = re.compile(
    rf"(?i)(?P<kind>{_LABEL}|{_CONTAINER})\s+(?P<num>{_NUMBER}|[A-Za-z]+)\b"
)
_URL = re.compile(
    r"(?i)(?:^|[/#?&=._-])"
    r"(?P<kind>articles?|arts?|sections?|secs?|chapters?|chaps?|chapitres?|"
    r"parts?|parties|titles?|titres?|paragrafs?|paragraphs?|madde|pasal|abschnitte?)"
    r"(?:[-_/=]|%20|\s)*"
    r"(?P<num>[0-9]{1,5}(?:\.[0-9]{1,4})?[a-z]?)"
)
_INSTRUMENT_STEM = re.compile(
    r"(?i)(?:gesetz|vertrag|beschlu[sß]|verordnung|kundmachung|bekanntmachung|"
    r"übereinkommen|uebereinkommen|abkommen|arr[eê]t[eé]|d[eé]cret|ordonnance)"
)
_INSTRUMENT_WORD = re.compile(
    r"(?i)\b(?:acts?|treat(?:y|ies)|gesetzes?|gesetz|codes?|lois?|"
    r"ordinances?|ordonnances?|abkommen|verfassung|constitutions?|statutes?|orders?|rules?|"
    r"regulations?|règlements?|reglements?|zakoni?|uredba|bekendtgørelser?|"
    r"bekendtgorelser?|loven|lov|decrees?|décrets?|decrets?|convenios?|"
    r"conventions?|protocols?|vertr(?:ag|äge|age)|charters?|proclamations?|"
    r"kodeks|wetten|wet|förordningar|forordninger|asetus|laki|códigos?|"
    r"codigos?|codice|byelaws?|by-laws?)\b"
)
_TEXT_HOST = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?("
    r"ris\.bka\.gv\.at|legifrance\.gouv\.fr|legislation\.gov\.uk|"
    r"retsinformation\.dk|laws-lois\.justice\.gc\.ca|legislation\.gov\.au|"
    r"irishstatutebook\.ie|eur-lex\.europa\.eu|canlii\.org|austlii\.edu\.au|"
    r"narodne-novine\.nn\.hr|[a-z0-9.-]+\.(?:gov|gouv|gv)\.[a-z]{2}|"
    r"[a-z0-9.-]+\.europa\.eu|[a-z0-9.-]+\.gov"
    r")\b"
)
_COLUMNS = (
    ("title", "title_number"),
    ("chapter", "chapter_number"),
    ("part", "part_number"),
    ("section", "section_number"),
    ("article", "article_number"),
)


@dataclass(frozen=True)
class HeadingAssignment:
    """One atom's heading, the evidence that produced it, and the scraped site."""

    status: str
    evidence: str
    site: str
    site_from: str
    instrument: str
    hierarchy_path: str
    locators: tuple[tuple[str, str], ...]

    def locator_map(self) -> dict[str, str]:
        return dict(self.locators)


def assign_heading(context: Mapping[str, object]) -> HeadingAssignment:
    """Fill a heading from source fields, the title, the opening line, or the URL.

    ``context`` accepts the source columns admission kept and the atom fields
    that survive on an already encoded row: title, text, citation, statute,
    source_url, hierarchy_kind, hierarchy_path, section_number, article_number,
    chapter_number, part_number, title_number, instrument_title,
    official_citation, official_identifier, source_type, and collector.
    """

    title = _clean(context.get("title"))
    title_loc, prefix = _from_title(title)
    text_loc: dict[str, str] = {}
    if not title_loc:
        text_loc = _from_opening(context.get("text"))
    column_loc, column_evidence = _from_columns(context)
    bare_article = _bare_article(context)
    if bare_article and _accept(title_loc or text_loc, bare_article) is None:
        bare_article = {}
    path_loc = _from_path(context.get("hierarchy_path"))
    url_loc, host = _from_url(context.get("source_url"))

    locators: dict[str, str] = {}
    evidence = ""

    def take(found: dict[str, str], name: str) -> None:
        nonlocal evidence
        if not found:
            return
        added = _accept(locators, found)
        if added is None:
            return
        if added:
            locators.update(added)
            if not evidence:
                evidence = name
        elif not evidence:
            evidence = name

    if column_loc:
        take(column_loc, column_evidence)
    take(bare_article, "source_field")
    take(path_loc, "hierarchy_path")
    take(title_loc, "title")
    take(text_loc, "text_heading")
    take(url_loc, "source_url")

    site, site_from = _site(context, host)
    instrument = _instrument(
        context,
        title,
        prefix,
        title_was_heading=bool(title_loc),
    )
    if locators:
        return _result(
            "structural",
            evidence or "title",
            site,
            site_from,
            instrument,
            locators,
        )
    if instrument:
        return _result("instrument_only", "instrument", site, site_from, instrument, {})
    return _result("unresolved", "site" if site else "none", site, site_from, "", {})


def _result(
    status: str,
    evidence: str,
    site: str,
    site_from: str,
    instrument: str,
    locators: dict[str, str],
) -> HeadingAssignment:
    ordered = tuple((key, locators[key]) for key in _LOCATOR_ORDER if key in locators)
    path = ""
    if ordered:
        labels = {
            "title": "Title",
            "chapter": "Chapter",
            "part": "Part",
            "article": "Article",
            "section": "Section",
        }
        shown = locators
        if shown.get("article") and shown.get("section") == shown.get("article"):
            shown = {key: value for key, value in shown.items() if key != "section"}
        path = " / ".join(
            f"{labels[key]} {shown[key]}" for key in _LOCATOR_ORDER if key in shown
        )
    return HeadingAssignment(status, evidence, site, site_from, instrument, path, ordered)


def _accept(existing: dict[str, str], new: dict[str, str]) -> dict[str, str] | None:
    """Keys to add. None means this source names a different provision."""

    old_numbers = {existing[key].casefold() for key in existing if key in _PROVISION}
    new_numbers = {new[key].casefold() for key in new if key in _PROVISION}
    if old_numbers and new_numbers and old_numbers != new_numbers:
        return None
    added: dict[str, str] = {}
    for key, value in new.items():
        current = existing.get(key)
        if current is not None and current.casefold() != value.casefold():
            return None
        if current is None:
            added[key] = value
    return added


def _from_title(title: str) -> tuple[dict[str, str], str]:
    label = " ".join(title.translate(_THAI_DIGITS).split())
    if not label:
        return {}, ""
    tailed = _TAILED.match(label)
    if tailed:
        placed = _tail_locators(tailed.group("rest"))
        if placed:
            return placed, _clean(tailed.group("name")).strip(" -–—")
    suffixed = _SUFFIX.match(label)
    if suffixed:
        kind = _kind_of(suffixed.group("kind"))
        number = _norm_num(suffixed.group("num"))
        if kind and number and not _is_year(number):
            return _article_also_section({kind: number}), _clean(suffixed.group("name")).strip(" -–—")
    leading = _LEADING.match(label)
    if leading:
        kind = _kind_of(leading.group("kind"))
        number = _norm_num(leading.group("num"))
        if kind and number and not _is_year(number):
            return _article_also_section({kind: number}), ""
    worded = _LEADING_WORD.match(label)
    if worded:
        kind = _kind_of(worded.group("kind"))
        number = _words_to_number(worded.group("num"))
        if kind and number:
            placed = {kind: number}
            if kind == "article":
                placed = _article_also_section(placed)
            return placed, ""
    annex = _annex_locator(label)
    if annex:
        return annex, ""
    container = _CONTAINER_LINE.match(label)
    if container:
        placed = _container(container.group("kind"), container.group("num"))
        if placed:
            return placed, ""
    duplicated = _DUPLICATE.match(label)
    if duplicated:
        number = _norm_num(duplicated.group(1))
        if number and not _is_year(number):
            return {"section": number}, ""
    dotted = _DOTTED.match(label)
    if dotted:
        number = _norm_num(dotted.group(1))
        if number and not _is_year(number):
            return {"section": number}, ""
    marginal = _MARGINAL.match(label)
    if marginal:
        number = _norm_num(marginal.group(1))
        if number and not _is_year(number):
            return {"section": number}, ""
    bare = _BARE.match(label)
    if bare:
        number = _norm_num(bare.group(1))
        if number and not _is_year(number):
            return {"section": number}, ""
    trailing = _TRAILING_CONTAINER.search(label)
    if trailing:
        placed = _container(trailing.group("kind"), trailing.group("num"))
        if placed:
            prefix = label[: trailing.start()].strip(" ,;-")
            return placed, prefix
    embedded: dict[str, str] = {}
    for match in _EMBEDDED_CONTAINER.finditer(label):
        embedded.update(_container(match.group("kind"), match.group("num")))
    if embedded:
        # Keep the surrounding instrument name. A short label is only the container.
        return embedded, label if len(label) > 48 else ""
    return {}, ""


def _from_opening(value: object) -> dict[str, str]:
    """Use the first line only. A later sentence that cites an article is not a heading."""

    if not isinstance(value, str):
        return {}
    line = ""
    for raw in value.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not line:
        return {}
    locators, _prefix = _from_title(line)
    return locators


def _from_columns(context: Mapping[str, object]) -> tuple[dict[str, str], str]:
    hierarchy = _hierarchy_kind(context.get("hierarchy_kind"))
    locators: dict[str, str] = {}
    for key, column in _COLUMNS:
        label_kind, number = _parse_field(context.get(column))
        if not number:
            continue
        if key == "article" and not label_kind:
            if hierarchy != "article":
                continue
            target = "article"
        elif label_kind == "section" and key == "article":
            target = "section"
        else:
            target = label_kind or key
        locators.setdefault(target, number)
    article = locators.get("article")
    section = locators.get("section")
    if article and section and article.casefold() != section.casefold():
        if hierarchy == "article":
            locators.pop("section", None)
        else:
            locators.pop("article", None)
    if "article" in locators:
        locators = _article_also_section(locators)
    if hierarchy in locators:
        return locators, "source_hierarchy"
    if locators:
        return locators, "source_field"
    return {}, ""


def _bare_article(context: Mapping[str, object]) -> dict[str, str]:
    """A bare article number is a provision only when the title does not disagree.

    The caller drops it when the title names a different article or section.
    """

    label_kind, number = _parse_field(context.get("article_number"))
    if label_kind or not number:
        return {}
    if _hierarchy_kind(context.get("hierarchy_kind")) == "article":
        return {}
    return _article_also_section({"article": number})


def _from_path(value: object) -> dict[str, str]:
    text = _clean(value).translate(_THAI_DIGITS)
    if not text:
        return {}
    locators: dict[str, str] = {}
    for match in _PATH.finditer(text):
        kind = _kind_of(match.group("kind"))
        number = _norm_num(match.group("num")) or _NUMBER_WORDS.get(match.group("num").casefold(), "")
        if kind and number and not _is_year(number):
            locators[kind] = number
    if "article" in locators:
        locators = _article_also_section(locators)
    return locators


def _from_url(value: object) -> tuple[dict[str, str], str]:
    raw = _clean(value)
    if not raw:
        return {}, ""
    parsed = urlsplit(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    locators: dict[str, str] = {}
    for target in (parsed.path, parsed.query, parsed.fragment):
        for match in _URL.finditer(target):
            kind = _kind_of(match.group("kind"))
            number = _norm_num(match.group("num"))
            if kind and number:
                locators[kind] = number
    if "article" in locators:
        locators = _article_also_section(locators)
    return locators, host


def _site(context: Mapping[str, object], host: str) -> tuple[str, str]:
    if host:
        return host, "source_url"
    for key in ("source_type", "collector"):
        name = _site_token(context.get(key))
        if name:
            return name, key
    text = context.get("text")
    if isinstance(text, str) and text:
        match = _TEXT_HOST.search(text[:800])
        if match:
            found = match.group(1).lower()
            if found.startswith("www."):
                found = found[4:]
            return found, "text"
    return "", ""


def _instrument(
    context: Mapping[str, object],
    title: str,
    prefix: str,
    *,
    title_was_heading: bool,
) -> str:
    named = _trusted_name(prefix)
    if named:
        return named
    named = _trusted_name(context.get("instrument_title"))
    if named:
        return named
    named = _trusted_name(context.get("official_citation"))
    if named and _citation_like(named):
        return named
    for key in ("statute", "citation", "official_identifier"):
        named = _citation_name(context.get(key))
        if named:
            return named
    if not title_was_heading:
        return _titled_instrument(title)
    return ""


def _trusted_name(value: object) -> str:
    text = " ".join(_clean(value).split())
    if len(text) < 8 or len(text) > 300 or text.isdigit():
        return ""
    if not re.search(r"[A-Za-zÀ-ÿ]", text):
        return ""
    if _pure_heading(text):
        return ""
    return text


def _citation_name(value: object) -> str:
    text = " ".join(_clean(value).split())
    if not _citation_like(text) or _pure_heading(text):
        return ""
    if _INSTRUMENT_WORD.search(text) or "/" in text:
        return text
    return ""


def _citation_like(text: str) -> bool:
    return (
        len(text) >= 6
        and not text.isdigit()
        and bool(re.search(r"[A-Za-zÀ-ÿ]", text))
        and bool(re.search(r"\d", text))
    )


def _titled_instrument(title: str) -> str:
    text = " ".join(title.split())
    if len(text) < 8 or len(text) > 300 or _pure_heading(text):
        return ""
    if (
        _INSTRUMENT_WORD.search(text)
        or _INSTRUMENT_STEM.search(text)
        or _mostly_upper(text)
        or _long_name(text)
    ):
        return text
    return ""


def _pure_heading(text: str) -> bool:
    locators, prefix = _from_title(text)
    if prefix:
        return False
    return bool(locators) and len(text) <= 48


def _long_name(title: str) -> bool:
    words = title.split()
    letters = sum(char.isalpha() for char in title)
    return len(words) >= 6 and letters >= 40


def _tail_locators(rest: str) -> dict[str, str]:
    locators: dict[str, str] = {}
    for match in _TAIL_PIECE.finditer(rest):
        kind = _kind_of(match.group("kind"))
        number = _norm_num(match.group("num"))
        if kind and number and not _is_year(number):
            locators[kind] = number
    if "article" in locators and "section" not in locators:
        locators = _article_also_section(locators)
    return locators


def _annex_locator(label: str) -> dict[str, str]:
    match = _ANNEX.match(label)
    if match is None:
        return {}
    pretty = {
        "annex": "Annex",
        "annexe": "Annexe",
        "annexes": "Annexe",
        "appendix": "Appendix",
        "appendices": "Appendix",
        "schedule": "Schedule",
        "schedules": "Schedule",
        "anlage": "Anlage",
        "anlagen": "Anlage",
        "anhang": "Anhang",
        "anhänge": "Anhang",
        "anexo": "Anexo",
        "anexos": "Anexo",
        "bijlage": "Bijlage",
        "bijlagen": "Bijlage",
    }
    label_word = pretty.get(match.group("label").casefold(), match.group("label"))
    extra = match.group("extra") or ""
    number = _norm_num(extra) if extra else ""
    value = f"{label_word} {number}".strip()
    kind = _kind_of(match.group("kind") or "")
    if kind == "article":
        return _article_also_section({"article": value})
    return {"section": value}


def _mostly_upper(title: str) -> bool:
    letters = [char for char in title if char.isalpha()]
    if len(letters) < 12 or len(title.split()) < 3:
        return False
    return sum(char.isupper() for char in letters) / len(letters) >= 0.75


def _article_also_section(locators: dict[str, str]) -> dict[str, str]:
    if "article" in locators and "section" not in locators:
        locators = dict(locators)
        locators["section"] = locators["article"]
    return locators


def _container(kind_word: str, raw_number: str) -> dict[str, str]:
    kind = _kind_of(kind_word)
    number = _norm_num(raw_number) or _NUMBER_WORDS.get(raw_number.casefold(), "")
    if not kind or not number or _is_year(number):
        return {}
    return {kind: number}


def _parse_field(value: object) -> tuple[str, str]:
    text = _clean(value).translate(_THAI_DIGITS)
    if not text or len(text) > 40:
        return "", ""
    match = _FIELD.match(text)
    if match is None:
        return "", ""
    number = _norm_num(match.group("num"))
    if not number or _is_year(number):
        return "", ""
    label = match.group("kind") or ""
    return (_kind_of(label) if label else ""), number


def _hierarchy_kind(value: object) -> str:
    text = _clean(value).casefold()
    if text in {"title", "chapter", "part", "article", "section"}:
        return text
    return ""


def _kind_of(word: str) -> str:
    token = word.casefold().strip(".")
    if token.startswith(("anl", "anh", "annex", "append", "schedul", "bijlage", "anexo")):
        return "section"
    if token.startswith("§") or token == "มาตรา":
        return "section" if token.startswith("§") else "article"
    if token.startswith((
        "art",
        "neni",
        "član",
        "clan",
        "madde",
        "pasal",
    )):
        return "article"
    if token.startswith((
        "sec",
        "abschn",
        "paragraf",
        "paragraph",
        "sekcj",
        "seccion",
        "sección",
    )):
        return "section"
    if token.startswith(("chap", "kapitel", "capit")):
        return "chapter"
    if token.startswith(("part", "partie", "teil")):
        return "part"
    if token.startswith("tit"):
        return "title"
    return ""


def _norm_num(raw: str) -> str:
    text = raw.strip().strip(".").translate(_THAI_DIGITS)
    if not text:
        return ""
    if re.fullmatch(r"[0-9]{1,5}", text):
        return str(int(text))
    if re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,6}", text):
        return text
    letters = re.fullmatch(r"([0-9]{1,4})([A-Za-z]{1,3})", text)
    if letters:
        suffix = letters.group(2)
        if suffix.casefold() in {"st", "nd", "rd", "th"}:
            return ""
        return letters.group(1) + suffix.upper()
    roman = text.upper()
    if re.fullmatch(r"[IVXLCDM]{1,8}", roman) and _ROMAN.fullmatch(roman):
        return roman
    return ""


def _words_to_number(raw: str) -> str:
    ones = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
    }
    teens = {
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
    }
    tens = {
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    parts = [part for part in re.split(r"[-\s]+", raw.casefold()) if part]
    if len(parts) == 1:
        value = ones.get(parts[0], teens.get(parts[0], tens.get(parts[0])))
        return "" if value is None else str(value)
    if len(parts) == 2 and parts[0] in tens and parts[1] in ones:
        return str(tens[parts[0]] + ones[parts[1]])
    return ""


def _is_year(number: str) -> bool:
    return _YEAR.fullmatch(number) is not None


def _site_token(value: object) -> str:
    text = _clean(value)
    if not text or len(text) > 80 or any(char.isspace() for char in text):
        return ""
    if not re.search(r"[A-Za-z]", text):
        return ""
    return text.casefold()


def _clean(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""
