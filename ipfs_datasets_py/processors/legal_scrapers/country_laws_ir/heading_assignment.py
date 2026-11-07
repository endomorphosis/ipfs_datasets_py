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
still finds the article. A title that is only a code provision, such as
``Article L111-2`` or ``Article 8-2``, is that provision. The body does not
have to repeat it. An annex title, a catalog id, and a body that opens on a
different article are not that provision. A parenthetical tail such as ``338(2)`` or
``Article 11(5)`` keeps that base and stores the tail as the subsection.
``المادة(35)`` is article 35: the number sits inside the parentheses, and
there is no subsection. A subsection by itself is not a heading. Lettered
codes may run to eight letters, as in ``103ZZGD``, and a decimal note may end
in a letter, as in ``10.72D``. A source hierarchy or an explicit section,
chapter, part, or title field wins over a title that names a different
number. A bare citation is used only as the instrument name when it reads as
one, never as the provision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

_LOCATOR_ORDER = ("title", "chapter", "part", "article", "section", "subsection")
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
_NUMBER = r"[0-9]{1,5}(?:\.[0-9]{1,4})?[A-Za-z]{0,8}|[IVXLCDM]{1,8}"
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
_MARGINAL = re.compile(r"^\*?([0-9]{1,5}(?:\.[0-9]{1,6})?[A-Za-z]{0,8})\s+\S")
_LEADING_WORD = re.compile(
    rf"(?i)^(?P<kind>{_LABEL})\s+(?P<num>[A-Za-z]+(?:[-\s]+[A-Za-z]+)?)\b"
)
_ANNEX = re.compile(
    r"(?i)^(?P<kind>articles?|art\.?|sections?|sec\.?|§+)?\s*"
    r"(?P<label>annexe?s?|appendices|appendix|schedules?|anlagen?|anh[aä]nge?|"
    r"anexos?|bijlagen?)"
    r"(?:\s+(?P<extra>[0-9]{1,4}|[IVXLCDM]{1,8}))?"
    r"\s*[.:;]?"
    r"(?:\s*\([^)]{0,48}\))?"
    r"(?:\s*[-–—]\s+(?P<caption>[^.]{1,80}))?"
    r"\s*$"
)
# A whole title that is only a code provision: "Article L22-10-38",
# "Section 4.6A", "Section 36Z2", "Section A.1", "Article D910-1 B",
# "Article R*712-8". The star is part of the French regulatory id.
_CODE_TITLE = re.compile(
    r"(?i)^(?P<kind>articles?|arts?\.?|sections?|secs?\.?)\s+"
    r"(?P<token>"
    r"(?:[A-Za-z]{1,4}\*?\s*\.?\s*)?"
    r"[0-9]{1,5}"
    r"(?:[.\-][0-9]{1,5}){0,4}"
    r"(?:[A-Za-z]{1,3}[0-9]{0,4})?"
    r"(?:\s+[A-Za-z]{1,3})?"
    r")"
    r"\s*[.:]?\s*$"
)
_LETTER_SECTION = re.compile(r"(?i)^(?:sections?|secs?\.?)\s+([A-Za-z])\s*$")
_CAP = re.compile(r"(?i)^cap\.?\s*([0-9]{1,4})\b\s*(.*)$")
_SI_TITLE = re.compile(
    r"(?i)^the\s+\S.{6,400}?\s(?:schemes?|warrants?|directions?)"
    r"(?:\s+\([^)]{0,80}\))*"
    r"(?:,?\s*(?:1[89][0-9]{2}|20[0-9]{2}))?"
    r"\s*$"
)
_MEASURE_TITLE = re.compile(
    r"(?i)^[A-Z].{6,240}?\smeasures?\s+(?:1[89][0-9]{2}|20[0-9]{2})\s*$"
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
# The number is inside the label: المادة(35) is article 35, not a subsection.
_WRAPPED_NUMBER = re.compile(
    r"(?i)^(?P<kind>s\.|sections?|secs?\.?|articles?|arts?\.?|المادة)\s*\(\s*(?P<num>[0-9]{1,5})\s*\)$"
)
# One tail only. 338(2) and s. 5(4) keep the base; 102(a)(1) does not match.
_PAREN_NUMBER = re.compile(
    r"(?i)^(?:(?P<kind>s\.|sections?|secs?\.?|articles?|arts?\.?)\s+)?"
    r"(?P<base>[0-9]{1,5}(?:\.[0-9]{1,4})?[A-Za-z]{0,8}|[IVXLCDM]{1,8})"
    r"\((?P<sub>[^)]*)\)$"
)
_PAREN_HEAD = re.compile(
    r"^(?P<base>[0-9]{1,5}(?:\.[0-9]{1,4})?[A-Za-z]{0,8})"
    r"\((?P<sub>[^)]*)\)"
    r"(?:\s+\S|\s*$)"
)
_IMMEDIATE_SUB = re.compile(r"^\s*\(([^)]*)\)")
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


_EXACT_LABEL = re.compile(
    r"(?i)^(?:sections?|secs?\.?|s\.)\s+([0-9]{1,4}[A-Za-z]{0,8})$"
)
_ACT_OPENING = re.compile(
    r"^([0-9]{1,4}[A-Za-z]{0,4})(?:\s+\1\b|\s+([A-Za-z]{2,}))"
)
_ACT_TITLE = re.compile(r"(?i)\bact\b")
_AMENDED_TITLE = re.compile(r"(?i)\bis amended\b")
_TITLE_YEAR = re.compile(r"\b(?:1[89][0-9]{2}|20[0-9]{2})\b")
_EXACT_DOT = re.compile(r"^([0-9]{1,4}[a-z]?)\.$")
_LEADING_SECTION_MARK = re.compile(r"^§+\s*([0-9]{1,4}[a-z]?)\b")
_SECTION_CAPTION = re.compile(
    r"^§+\s*([0-9]{1,4}[a-z]?)(?:\s+[A-ZÄÖÜÀ-Ý][^.]{0,180})?$"
)
_EXACT_ART = re.compile(r"(?i)^(?:art\.?|article)\s+([0-9]{1,4}[a-z]?)$")
_LETTERED = re.compile(r"^([0-9]{1,4}[A-Za-z]{1,8})\s+(\S+)")
_DECIMAL = re.compile(r"^([0-9]{1,4}\.[0-9]{1,4})\s+(\S+)")
_HYPHEN_SECTION = re.compile(r"^([0-9]{1,4})-([0-9]{1,4})([A-Za-z]?)\s+(\S+)")
_EXACT_CLANAK = re.compile(r"(?i)^članak\s+([0-9]{1,4}[a-z]?)\.?$")
_EXACT_S_DOT = re.compile(r"(?i)^s\.\s+([0-9]{1,4}[A-Za-z]{0,4})\.$")
_TRIPLE = re.compile(
    r"^([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})([A-Za-z]{0,3})\.?(?:\s+(.*))?$"
)
_FORM_SECTION = re.compile(
    r"(?i)^section\s+([0-9]{1,4}\.[0-9]{1,4}[A-Za-z]{0,4}-[A-Za-z]{2,12})$"
)
_FORM_TOKEN = re.compile(
    r"^([0-9]{1,4}\.[0-9]{1,4}[A-Za-z]{0,4}-[A-Za-z]{2,12})(?:\s+(\S+))?$"
)
_CA_REG = re.compile(
    r"^([A-Z])\.([0-9]{2})([A-Z])?\.([0-9]{3})([A-Z])?(?:\.([0-9]{1,2}))?\.?(?:\s+(.*))?$"
)
_ARTYKUL = re.compile(r"(?i)^artyku([lł])\s+([0-9]{1,4}[a-z]?)\b")
# Nominative only. "3. punktu", "3. punkta", and "3. punkti" are not headings.
_PUNKTS_TITLE = re.compile(r"^([0-9]{1,4})\.\s*punkts\.?$")
_CROSS = frozenset({"of", "and", "or", "to"})
_PAGE_WORD = re.compile(r"(?i)\bpage\b")
_STREET = re.compile(
    r"(?i)^(?:east|west|north|south|street|road|avenue|lane|drive|boulevard|st|rd|ave)\.?$"
)


def _provision_number(number: str) -> str:
    token = number.strip()
    if not token or _is_year(token):
        return ""
    head = token.split(".", 1)[0]
    if head.isdigit() and (int(head) <= 0 or int(head) > 2000):
        return ""
    return token


def locators_from_provision_label(
    title: object,
    statute: object = "",
    text: object = "",
) -> dict[str, str]:
    """Read a provision number that is already the label of the atom.

    ``Section 59``, ``1.`` confirmed by the same statute number, a leading
    ``§ 1`` confirmed the same way, ``§ 13 Satzung``, ``Art 3``, an Irish
    ``1 1.`` opening, a lettered marginal note such as ``15AB`` or
    ``126AKDG``, a decimal note such as ``6.1``, a hyphenated note such as
    ``57-1``, ``Članak 8.``, an exact ``s. 5.``, a three-part marginal note
    such as ``5.19.1``, a suffixed form such as ``4.34A-CVL``, a regulation
    note such as ``C.01A.001`` when that same note opens the statute, and
    ``Artykuł 24`` when the statute opens with that article are provision
    locators. A street address, a page line, and a cross reference are not.
    ``C.01A.001`` is never stored as section 1.
    """

    label = " ".join(_clean(title).translate(_THAI_DIGITS).split())
    cited = _clean(statute)
    if not label:
        return {}
    exact = _EXACT_LABEL.match(label)
    if exact:
        number = _provision_number(exact.group(1))
        if number and (not cited or cited.casefold() == number.casefold() or not _FIELD.fullmatch(cited)):
            return {"section": number}
        return {}
    dotted = _EXACT_DOT.match(label)
    if dotted:
        number = _provision_number(dotted.group(1))
        if number and cited.casefold() == number.casefold():
            return {"section": number}
        return {}
    marked = _LEADING_SECTION_MARK.match(label)
    if marked:
        number = _provision_number(marked.group(1))
        if number and cited.casefold() == number.casefold():
            return {"section": number}
    caption = _SECTION_CAPTION.match(label)
    if caption:
        number = _provision_number(caption.group(1))
        if number:
            return {"section": number}
        return {}
    article = _EXACT_ART.match(label)
    if article:
        number = _provision_number(article.group(1))
        if number:
            return {"article": number, "section": number}
        return {}
    clanak = _EXACT_CLANAK.match(label)
    if clanak:
        number = _provision_number(clanak.group(1))
        if number:
            return {"article": number, "section": number}
        return {}
    artykul = _artykul_section(label, text)
    if artykul:
        return artykul
    dotted_s = _EXACT_S_DOT.match(label)
    if dotted_s:
        number = _provision_number(dotted_s.group(1))
        if number:
            return {"section": number}
        return {}
    duplicated = _DUPLICATE.match(label)
    if duplicated:
        number = _provision_number(duplicated.group(1))
        if number:
            return {"section": number}
        return {}
    lettered = _LETTERED.match(label)
    if lettered and re.search(r"[A-Za-z]", lettered.group(1)):
        number = _provision_number(lettered.group(1))
        if number and _STREET.match(lettered.group(2)) is None:
            return {"section": number}
        return {}
    decimal = _DECIMAL.match(label)
    if decimal:
        number = _provision_number(decimal.group(1))
        if number and _STREET.match(decimal.group(2)) is None:
            return {"section": number}
    hyphen = _hyphen_section(label)
    if hyphen:
        return {"section": hyphen}
    triple = _triple_section(label, text)
    if triple:
        return {"section": triple}
    regulation = _regulation_section(label, text)
    if regulation:
        return {"section": regulation}
    form = _form_section(label, text)
    if form:
        return {"section": form}
    opening = _act_opening(label, text)
    if opening:
        return {"section": opening}
    return {}


def _hyphen_section(label: str) -> str:
    """Read an Australian-style ``57-1`` marginal note. A street range is not one."""

    found = _HYPHEN_SECTION.match(label)
    if found is None:
        return ""
    left, right, suffix, word = found.groups()
    if _is_year(left) or _STREET.match(word) is not None or _PAGE_WORD.search(label):
        return ""
    if int(left) <= 0 or int(left) > 2000 or int(right) <= 0 or int(right) > 2000:
        return ""
    if any(_STREET.match(token) is not None for token in label.split()):
        return ""
    return f"{left}-{right}{suffix}"


def _triple_section(label: str, text: object) -> str:
    """Read a marginal note such as ``5.19.1``. A year or a street is not one."""

    found = _TRIPLE.match(label)
    if found is None:
        return ""
    left, mid, right, letters, rest = found.groups()
    if _is_year(left) or any(int(part) <= 0 or int(part) > 2000 for part in (left, mid, right)):
        return ""
    if _PAGE_WORD.search(label) or any(_STREET.match(token) is not None for token in label.split()):
        return ""
    rest = rest or ""
    first = rest.split(None, 1)[0].casefold().strip(":") if rest else ""
    if first in _CROSS:
        return ""
    token = f"{int(left)}.{int(mid)}.{int(right)}{letters}"
    body = " ".join(_clean(text).split())
    if body and re.search(rf"(?<![0-9]){re.escape(token)}(?![0-9])", body[:240]) is None:
        return ""
    return token


def _regulation_section(label: str, text: object) -> str:
    """Read a regulation note such as ``C.01A.001``. A bare title is not one."""

    found = _CA_REG.match(label)
    if found is None:
        return ""
    letter, two, mid_letter, three, end_letter, extra, rest = found.groups()
    token = f"{letter}.{two}{mid_letter or ''}.{three}{end_letter or ''}"
    if extra:
        token = f"{token}.{extra}"
    if _PAGE_WORD.search(label) or any(_STREET.match(word) is not None for word in label.split()):
        return ""
    rest = rest or ""
    first = rest.split(None, 1)[0].casefold().strip(":") if rest else ""
    if first in _CROSS:
        return ""
    body = " ".join(_clean(text).split())
    if not body:
        return ""
    if re.search(rf"(?<![A-Z0-9.]){re.escape(token)}(?![0-9A-Z])", body[:240]) is None:
        return ""
    return token


def locators_from_punkts_title(title: object, text: object = "") -> dict[str, str]:
    """Read a nominative ``3. punkts`` title when the statute opens on that number.

    The Latvian body starts ``3. `` and does not repeat the word. Declined
    titles, an empty body, a year, and a different opening number are not
    this provision. ``1. pants`` is a different heading and is left alone.
    """

    label = " ".join(_clean(title).split()).casefold()
    found = _PUNKTS_TITLE.fullmatch(label)
    if found is None:
        return {}
    number = _provision_number(found.group(1))
    if not number:
        return {}
    body = _clean(text).lstrip()
    if re.match(rf"{re.escape(number)}\.(?!\d)", body) is None:
        return {}
    return {"article": number, "section": number}


def locators_from_code_title(title: object, text: object = "") -> dict[str, str]:
    """Read a title that is only a code provision, such as ``Article L111-2``.

    Legifrance stores ``Article 8-2`` or ``Article L111-2`` on the row. The
    statute body does not repeat that heading. An annex, a catalog id, a
    title with extra words, an empty body, and a body that opens on a
    different article or section of the same kind are not this provision.
    A paragraph that starts ``1.`` inside the article is not a conflict.
    """

    label = " ".join(_clean(title).split())
    if not label:
        return {}
    coded = _CODE_TITLE.match(label)
    if coded is None:
        return {}
    kind = _kind_of(coded.group("kind"))
    number = _norm_code(coded.group("token"))
    if kind not in {"article", "section"} or not number:
        return {}
    body = _clean(text).strip()
    if not body:
        return {}
    opened = _from_opening(body).get(kind, "")
    if opened and opened.casefold() != number.casefold():
        return {}
    if kind == "article":
        return {"article": number, "section": number}
    return {"section": number}


def _artykul_section(label: str, text: object) -> dict[str, str]:
    """Read ``Artykuł 24`` when the statute itself opens with that article."""

    found = _ARTYKUL.match(label)
    if found is None:
        return {}
    number = _provision_number(found.group(2))
    if not number:
        return {}
    rest = label[found.end():].strip(" .,;")
    first = rest.split(None, 1)[0].casefold().strip(".,:;") if rest else ""
    if first in _CROSS:
        return {}
    body = " ".join(_clean(text).split())
    if not body:
        return {}
    if re.match(rf"(?i)artyku[lł]\s+{re.escape(number)}(?![0-9])", body) is None:
        return {}
    return {"article": number, "section": number}


def _form_section(label: str, text: object) -> str:
    """Keep a suffixed form such as ``4.34A-CVL`` instead of cutting it at the hyphen."""

    exact = _FORM_SECTION.match(label)
    extra = ""
    if exact is not None:
        token = exact.group(1)
    else:
        opened = _FORM_TOKEN.match(label)
        if opened is None:
            return ""
        token = opened.group(1)
        extra = opened.group(2) or ""
    if extra and (_STREET.match(extra) is not None or extra.casefold() in _CROSS):
        return ""
    head = token.split(".", 1)[0]
    if not _provision_number(head):
        return ""
    body = " ".join(_clean(text).split())
    if body and not body.startswith(token):
        return ""
    return token


def _act_opening(label: str, text: object) -> str:
    """Use the section number that opens an Act when the title is that Act."""

    if not _ACT_TITLE.search(label) or _AMENDED_TITLE.search(label) or _TITLE_YEAR.search(label) is None:
        return ""
    body = " ".join(_clean(text).translate(_THAI_DIGITS).split())
    found = _ACT_OPENING.match(body)
    if found is None:
        return ""
    word = found.group(2) or ""
    if word and _STREET.match(word) is not None:
        return ""
    return _provision_number(found.group(1))


def locators_from_marked_title(title: object) -> tuple[dict[str, str], str]:
    """Read a provision pinned on the end of an instrument title.

    ``Einrichtung der Gerichtsbehörden - § 1`` is section 1 of that law.
    A street number, a cross reference, and a bare ``1.`` line are not pins.
    """

    label = " ".join(_clean(title).translate(_THAI_DIGITS).split())
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
            return (
                _article_also_section({kind: number}),
                _clean(suffixed.group("name")).strip(" -–—"),
            )
    return {}, ""


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
            "subsection": "Subsection",
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
            placed = _article_also_section({kind: number})
            _attach_subsection(placed, _immediate_subsection(label[leading.end():]))
            return placed, ""
    worded = _LEADING_WORD.match(label)
    if worded:
        kind = _kind_of(worded.group("kind"))
        number = _words_to_number(worded.group("num"))
        if kind and number:
            placed = {kind: number}
            if kind == "article":
                placed = _article_also_section(placed)
            return placed, ""
    coded = _CODE_TITLE.match(label)
    if coded:
        kind = _kind_of(coded.group("kind"))
        number = _norm_code(coded.group("token"))
        if kind and number:
            placed = {kind: number}
            if kind == "article":
                placed = _article_also_section(placed)
            return placed, ""
    lettered_section = _LETTER_SECTION.match(label)
    if lettered_section:
        return {"section": lettered_section.group(1).upper()}, ""
    annex, annex_prefix = _annex_locator(label)
    if annex:
        return annex, annex_prefix
    capped = _CAP.match(label)
    if capped:
        number = _norm_num(capped.group(1))
        if number and not _is_year(number):
            return {"chapter": number}, _clean(capped.group(2)).strip(" -–—:.")
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
    headed = _parenthetical_heading(label)
    if headed:
        return headed, ""
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
    pending: list[tuple[str, str]] = []
    for key, column in _COLUMNS:
        label_kind, number, subsection = _parse_provision(context.get(column))
        if not number:
            continue
        # A tail on a title, chapter, or part is not that container's number.
        if subsection and key not in _PROVISION:
            continue
        if key == "article" and not label_kind:
            if hierarchy != "article":
                if subsection:
                    pending.append((number, subsection))
                continue
            target = "article"
        elif label_kind == "section" and key == "article":
            target = "section"
        else:
            target = label_kind or key
        if target not in {"title", "chapter", "part", "article", "section"}:
            continue
        locators.setdefault(target, number)
        if subsection:
            pending.append((number, subsection))
    article = locators.get("article")
    section = locators.get("section")
    if article and section and article.casefold() != section.casefold():
        if hierarchy == "article":
            locators.pop("section", None)
        else:
            locators.pop("article", None)
    if "article" in locators:
        locators = _article_also_section(locators)
    _attach_pending_subsection(locators, pending)
    if hierarchy in locators:
        return locators, "source_hierarchy"
    if locators:
        return locators, "source_field"
    return {}, ""


def _bare_article(context: Mapping[str, object]) -> dict[str, str]:
    """A bare article number is a provision only when the title does not disagree.

    The caller drops it when the title names a different article or section.
    """

    label_kind, number, subsection = _parse_provision(context.get("article_number"))
    if label_kind or not number or subsection:
        return {}
    if _hierarchy_kind(context.get("hierarchy_kind")) == "article":
        return {}
    return _article_also_section({"article": number})


def _from_path(value: object) -> dict[str, str]:
    text = _clean(value).translate(_THAI_DIGITS)
    if not text:
        return {}
    locators: dict[str, str] = {}
    subsection = ""
    for match in _PATH.finditer(text):
        kind = _kind_of(match.group("kind"))
        number = _norm_num(match.group("num")) or _NUMBER_WORDS.get(match.group("num").casefold(), "")
        if kind and number and not _is_year(number):
            locators[kind] = number
            if kind in _PROVISION:
                found = _immediate_subsection(text[match.end():])
                if found:
                    subsection = found
    if "article" in locators:
        locators = _article_also_section(locators)
    _attach_subsection(locators, subsection)
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
    if len(text) < 8 or len(text) > 1200 or _pure_heading(text):
        return ""
    if (
        _INSTRUMENT_WORD.search(text)
        or _INSTRUMENT_STEM.search(text)
        or _mostly_upper(text)
        or _long_name(text)
        or _SI_TITLE.match(text)
        or _MEASURE_TITLE.match(text)
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


def _annex_locator(label: str) -> tuple[dict[str, str], str]:
    match = _ANNEX.match(label)
    if match is None:
        return {}, ""
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
    caption = " ".join((match.group("caption") or "").split())
    if kind == "article":
        return _article_also_section({"article": value}), caption
    return {"section": value}, caption


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
    kind, number, _subsection = _parse_provision(value)
    return kind, number


def _parse_provision(value: object) -> tuple[str, str, str]:
    """Return the label kind, the provision number, and a subsection tail."""

    text = _clean(value).translate(_THAI_DIGITS)
    if not text or len(text) > 40:
        return "", "", ""
    wrapped = _WRAPPED_NUMBER.match(text)
    if wrapped:
        number = _norm_num(wrapped.group("num"))
        if number and not _is_year(number):
            return _provision_kind(wrapped.group("kind")), number, ""
        return "", "", ""
    parenthetical = _PAREN_NUMBER.match(text)
    if parenthetical:
        number = _norm_num(parenthetical.group("base"))
        subsection = _norm_subsection(parenthetical.group("sub"))
        if number and subsection and not _is_year(number):
            label = parenthetical.group("kind") or ""
            kind = _provision_kind(label) if label else ""
            return kind, number, subsection
        return "", "", ""
    match = _FIELD.match(text)
    if match is None:
        return "", "", ""
    number = _norm_num(match.group("num"))
    if not number or _is_year(number):
        return "", "", ""
    label = match.group("kind") or ""
    return (_provision_kind(label) if label else ""), number, ""


def _provision_kind(word: str) -> str:
    token = word.casefold().strip().strip(".")
    if token == "s":
        return "section"
    if word.strip() == "المادة":
        return "article"
    return _kind_of(word)


def _parenthetical_heading(label: str) -> dict[str, str]:
    match = _PAREN_HEAD.match(label)
    if match is None:
        return {}
    number = _norm_num(match.group("base"))
    subsection = _norm_subsection(match.group("sub"))
    if not number or not subsection or _is_year(number):
        return {}
    return {"section": number, "subsection": subsection}


def _immediate_subsection(tail: str) -> str:
    match = _IMMEDIATE_SUB.match(tail)
    if match is None:
        return ""
    return _norm_subsection(match.group(1))


def _attach_subsection(locators: dict[str, str], subsection: str) -> None:
    if not subsection or "subsection" in locators:
        return
    if any(key in locators for key in _PROVISION):
        locators["subsection"] = subsection


def _attach_pending_subsection(
    locators: dict[str, str],
    pending: list[tuple[str, str]],
) -> None:
    if not pending or "subsection" in locators:
        return
    accepted = {
        locators[key].casefold()
        for key in _PROVISION
        if key in locators
    }
    if not accepted:
        return
    chosen = ""
    for base, subsection in pending:
        if base.casefold() not in accepted:
            continue
        if chosen and chosen.casefold() != subsection.casefold():
            return
        chosen = subsection
    _attach_subsection(locators, chosen)


def _norm_subsection(raw: str) -> str:
    text = raw.strip()
    if not text or any(char.isspace() for char in text):
        return ""
    if re.fullmatch(r"[0-9]{1,4}", text):
        number = str(int(text))
        if _is_year(number):
            return ""
        return number
    if re.fullmatch(r"[A-Za-z]", text):
        return text
    roman = text.upper()
    if 2 <= len(roman) <= 8 and _ROMAN.fullmatch(roman):
        return roman
    return ""


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


# Ordinals and words glued onto a digit are not section letters. 153ZIKA stays:
# a vowel count would reject that real Australian section.
_LETTER_WORDS = frozenset({
    "st", "nd", "rd", "th",
    "of", "the", "ofthe", "and", "for", "with", "from",
    "this", "that", "which", "under", "into", "onto", "over", "upon",
    "other", "such", "than", "then", "them", "they",
    "have", "been", "were", "was", "are", "not", "but", "its",
    "any", "all", "may", "shall", "must", "per",
})


def _norm_num(raw: str) -> str:
    text = raw.strip().strip(".").translate(_THAI_DIGITS)
    if not text:
        return ""
    if re.fullmatch(r"[0-9]{1,5}", text):
        return str(int(text))
    decimal = re.fullmatch(r"([0-9]{1,5})\.([0-9]{1,6})([A-Za-z]{0,3})", text)
    if decimal:
        integer, fraction, letters = decimal.groups()
        if letters and (len(fraction) > 4 or letters.casefold() in _LETTER_WORDS):
            return ""
        return f"{int(integer)}.{fraction}{letters.upper()}"
    letters = re.fullmatch(r"([0-9]{1,4})([A-Za-z]{1,8})", text)
    if letters:
        suffix = letters.group(2)
        if suffix.casefold() in _LETTER_WORDS:
            return ""
        return letters.group(1) + suffix.upper()
    roman = text.upper()
    if re.fullmatch(r"[IVXLCDM]{1,8}", roman) and _ROMAN.fullmatch(roman):
        return roman
    return ""


def _norm_code(token: str) -> str:
    """Canonical form of a lettered provision such as L22-10-38 or 36Z2."""

    match = re.fullmatch(
        r"(?i)(?P<prefix>[A-Za-z]{1,4})?(?P<star>\*?)(?P<dot>\.?)(?P<gap>\s*)"
        r"(?P<num>[0-9]{1,5}(?:[.\-][0-9]{1,5}){0,4})"
        r"(?P<mid>[A-Za-z]{1,3})?(?P<tailnum>[0-9]{1,4})?"
        r"(?:\s+(?P<suffix>[A-Za-z]{1,3}))?",
        " ".join(token.split()),
    )
    if match is None:
        return ""
    prefix = match.group("prefix") or ""
    star = match.group("star") or ""
    if star and not prefix:
        return ""
    mid = match.group("mid") or ""
    tailnum = match.group("tailnum") or ""
    suffix = match.group("suffix") or ""
    if mid.casefold() in {"st", "nd", "rd", "th"} and not prefix and not tailnum and not suffix:
        return ""
    number = match.group("num")
    head = re.split(r"[.\-]", number, maxsplit=1)[0]
    if (
        not prefix
        and not mid
        and not tailnum
        and not suffix
        and re.fullmatch(r"[0-9]{4}", number)
        and head.isdigit()
        and _is_year(str(int(head)))
    ):
        return ""
    dot = "." if prefix and match.group("dot") else ""
    body = f"{prefix.upper()}{star}{dot}{number}{mid.upper()}{tailnum}"
    if suffix:
        body = f"{body} {suffix.upper()}"
    return body


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
    ordinals = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
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
    teen_ordinals = {
        "tenth": 10,
        "eleventh": 11,
        "twelfth": 12,
        "thirteenth": 13,
        "fourteenth": 14,
        "fifteenth": 15,
        "sixteenth": 16,
        "seventeenth": 17,
        "eighteenth": 18,
        "nineteenth": 19,
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
    ten_ordinals = {
        "twentieth": 20,
        "thirtieth": 30,
        "fortieth": 40,
        "fiftieth": 50,
        "sixtieth": 60,
        "seventieth": 70,
        "eightieth": 80,
        "ninetieth": 90,
    }
    parts = [part for part in re.split(r"[-\s]+", raw.casefold()) if part]
    if len(parts) == 1:
        value = ones.get(parts[0])
        if value is None:
            value = ordinals.get(parts[0])
        if value is None:
            value = teens.get(parts[0])
        if value is None:
            value = teen_ordinals.get(parts[0])
        if value is None:
            value = tens.get(parts[0])
        if value is None:
            value = ten_ordinals.get(parts[0])
        return "" if value is None else str(value)
    if len(parts) == 2 and parts[0] in tens and parts[1] in ones:
        return str(tens[parts[0]] + ones[parts[1]])
    if len(parts) == 2 and parts[0] in tens and parts[1] in ordinals:
        return str(tens[parts[0]] + ordinals[parts[1]])
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
