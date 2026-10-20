"""Directory of one nation's assembled laws.

Reads legal-record rows after a corpus is assembled. Each row that fits the
national schema becomes one code listing, with a Bluebook citation where a
published form is known and a Bluebook analog otherwise. A code name or a
heading that is still in the text is filed when the record title is only an
article caption. Rows that do not fit, provisions that cannot be placed, and
dense numbering holes are written beside the listing. This module does not
rewrite statute text, does not download, and does not upload.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    _DEFAULT_NAMES,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    LEGAL_RECORD_FIELDS,
    _INSTRUMENTS,
)

DIRECTORY_VERSION = "national-directory/v1"
_SORT_LIMIT = 250_000
_GAP_MIN_PRESENT = 4
_GAP_MAX_SPAN = 400
_GAP_MIN_DENSITY = 0.75
_LOCATORS = ("title", "chapter", "part", "article", "section")
_NUMBER = re.compile(r"^[0-9]{1,5}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_LABELS = {
    "US": "United States",
    "EU": "European Union",
    "GB": "United Kingdom",
}
# Published code abbreviations. Anything else stays an analog.
_CODE_FORMS: tuple[tuple[str, str, str, str], ...] = (
    ("US", "united states code", "U.S.C.", "section"),
    ("US", "code of federal regulations", "C.F.R.", "section"),
    ("FR", "code civil", "C. civ.", "article"),
    ("FR", "code penal", "C. pén.", "article"),
    ("FR", "code de commerce", "C. com.", "article"),
    ("DE", "burgerliches gesetzbuch", "BGB", "section"),
    ("DE", "strafgesetzbuch", "StGB", "section"),
    ("DE", "handelsgesetzbuch", "HGB", "section"),
    ("DE", "grundgesetz", "GG", "article"),
)
_TITLE_PREFIX = frozenset({"U.S.C.", "C.F.R."})
_EU_ACT = re.compile(
    r"(?i)\b(regulation|directive|decision)\b[^\n]{0,80}?\b((?:\(EU\)\s*)?\d{4}/\d+)\b"
)


@dataclass
class DirectoryEntry:
    jurisdiction: str
    instrument: str
    title: str
    book: str
    chapter: str
    part: str
    article: str
    section: str
    citation: str
    citation_form: str
    path: str
    entry_cid: str

    def as_dict(self) -> dict[str, str]:
        return {
            "jurisdiction": self.jurisdiction,
            "instrument": self.instrument,
            "title": self.title,
            "book": self.book,
            "chapter": self.chapter,
            "part": self.part,
            "article": self.article,
            "section": self.section,
            "citation": self.citation,
            "citation_form": self.citation_form,
            "path": self.path,
            "entry_cid": self.entry_cid,
        }


@dataclass
class DirectoryIndex:
    entries: list[DirectoryEntry] = field(default_factory=list)
    schema_problems: list[dict[str, str]] = field(default_factory=list)
    unplaced: list[dict[str, str]] = field(default_factory=list)
    gaps: list[dict[str, object]] = field(default_factory=list)
    duplicates: int = 0
    weak_instrument: int = 0

    def report(self) -> dict[str, object]:
        bluebook = sum(1 for entry in self.entries if entry.citation_form == "bluebook")
        return {
            "version": DIRECTORY_VERSION,
            "listed": len(self.entries),
            "bluebook": bluebook,
            "bluebook_analog": len(self.entries) - bluebook,
            "schema_problems": len(self.schema_problems),
            "unplaced": len(self.unplaced),
            "gaps": len(self.gaps),
            "duplicates": self.duplicates,
            "weak_instrument": self.weak_instrument,
        }


def index_national_laws(records: Iterable[Mapping[str, object]]) -> DirectoryIndex:
    """File assembled legal records into a national code listing."""

    index = DirectoryIndex()
    seen: set[tuple[str, ...]] = set()
    numbers: dict[tuple[str, ...], tuple[str, set[int]]] = {}
    for record in records:
        problems = _schema_problems(record)
        if problems:
            index.schema_problems.extend(problems)
            continue
        entry = _entry(record)
        if entry is None:
            index.unplaced.append(_unplaced(record))
            continue
        key = _entry_key(entry)
        if key in seen:
            index.duplicates += 1
        else:
            seen.add(key)
            index.entries.append(entry)
            if _weak_instrument(entry):
                index.weak_instrument += 1
        _note_number(numbers, entry)
    index.gaps.extend(_gaps(numbers))
    index.entries.sort(key=_sort_key)
    return index


def write_national_directory(source_dir: Path | str, dest_dir: Path | str) -> dict[str, object]:
    """Write the listing, schema problems, unplaced rows, and numbering gaps.

    ``source_dir`` is one finished country folder of legal-record parts.
    The corpus files are only read.
    """

    source = Path(source_dir)
    destination = Path(dest_dir)
    parts = sorted(source.glob("part-*.parquet"))
    if not parts:
        raise ValueError("source")
    destination.mkdir(parents=True, exist_ok=True)
    rows = _parquet_rows(parts)
    total = sum(count for _part, count in rows)
    if total > _SORT_LIMIT:
        report = _write_streaming(parts, destination, total)
    else:
        records = _iter_records(parts)
        index = index_national_laws(records)
        report = index.report()
        report["order"] = "code"
        _write_jsonl(destination / "directory.jsonl", (entry.as_dict() for entry in index.entries))
        _write_jsonl(destination / "schema_problems.jsonl", index.schema_problems)
        _write_jsonl(destination / "unplaced.jsonl", index.unplaced)
        _write_jsonl(destination / "gaps.jsonl", index.gaps)
    report["source_dir"] = str(source)
    report["source_rows"] = total
    report["files"] = [path.name for path in parts]
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _write_streaming(parts: list[Path], destination: Path, total: int) -> dict[str, object]:
    """Stream a corpus that is too large to sort in memory."""

    seen: set[tuple[str, ...]] = set()
    numbers: dict[tuple[str, ...], tuple[str, set[int]]] = {}
    listed = 0
    bluebook = 0
    duplicates = 0
    weak = 0
    schema_count = 0
    unplaced_count = 0
    with (destination / "directory.jsonl").open("w", encoding="utf-8") as directory, (
        destination / "schema_problems.jsonl"
    ).open("w", encoding="utf-8") as problems, (destination / "unplaced.jsonl").open(
        "w", encoding="utf-8"
    ) as unplaced:
        for record in _iter_records(parts):
            found = _schema_problems(record)
            if found:
                schema_count += len(found)
                for problem in found:
                    problems.write(json.dumps(problem, sort_keys=True, ensure_ascii=False) + "\n")
                continue
            entry = _entry(record)
            if entry is None:
                unplaced_count += 1
                unplaced.write(json.dumps(_unplaced(record), sort_keys=True, ensure_ascii=False) + "\n")
                continue
            key = _entry_key(entry)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            listed += 1
            if _weak_instrument(entry):
                weak += 1
            if entry.citation_form == "bluebook":
                bluebook += 1
            _note_number(numbers, entry)
            directory.write(json.dumps(entry.as_dict(), sort_keys=True, ensure_ascii=False) + "\n")
    gaps = _gaps(numbers)
    _write_jsonl(destination / "gaps.jsonl", gaps)
    return {
        "version": DIRECTORY_VERSION,
        "listed": listed,
        "bluebook": bluebook,
        "bluebook_analog": listed - bluebook,
        "schema_problems": schema_count,
        "unplaced": unplaced_count,
        "gaps": len(gaps),
        "duplicates": duplicates,
        "weak_instrument": weak,
        "order": "source",
        "source_rows": total,
    }


def _schema_problems(record: Mapping[str, object]) -> list[dict[str, str]]:
    cid = _text(record.get("entry_cid")) or _text(record.get("title")) or ""
    problems: list[dict[str, str]] = []

    def add(reason: str) -> None:
        problems.append({"entry_cid": cid, "reason": reason})

    for name in ("jurisdiction", "admin_level", "instrument_type", "text", "provenance"):
        if name not in record:
            add("missing_" + name)
    if problems:
        return problems
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        add("empty_text")
    admin = _text(record.get("admin_level"))
    if admin != "country":
        add("not_national")
    instrument = _text(record.get("instrument_type"))
    if instrument not in _INSTRUMENTS:
        add("bad_instrument")
    resolved = resolve_jurisdiction(_text(record.get("jurisdiction")))
    if resolved is None or resolved.admin_level not in {"country", "supranational"}:
        add("bad_jurisdiction")
    digest = record.get("content_sha256")
    if not isinstance(digest, str) or _SHA.fullmatch(digest) is None:
        add("bad_hash")
    provenance = _provenance(record.get("provenance"))
    if provenance is None:
        add("bad_provenance")
    elif provenance.get("document_role") != "law":
        add("not_law")
    return problems


_HEADING_LINE = re.compile(
    r"(?i)^(partie|livre|titre|titulo|título|chapitre|chapter|section|part)\s*-\s*"
    r"(?:partie|livre|titre|chapitre|chapter|section|part(?:ie)?)?\s*"
    r"([0-9]{1,4}|[IVXLCDM]{1,12})\b"
)
_ARTICLE_DOT = re.compile(
    r"(?i)^(?:article|art\.?)?\s*"
    r"((?:[A-Z]-)?[0-9]{1,4}(?:\s*[-.]\s*[0-9]{1,4})?)\s*\.-\s*$"
)
_ARTICLE_ONLY = re.compile(
    r"(?i)^(?:article|art\.?)\s+"
    r"((?:[A-Z]-)?[0-9]{1,4}(?:-[0-9]{1,4})?[A-Za-z]?)\s*[.:]?\s*$"
)
_SECTION_ONLY = re.compile(r"(?i)^(?:section|sec\.?)\s+([0-9]{1,4}[A-Za-z]?)\s*[.:]?\s*$")
_TITLE_SECTION = re.compile(r"(?i)^(?:section|sec\.?)\s+([0-9]{1,4}[A-Za-z]?)\b")
_TITLE_ARTICLE = re.compile(
    r"(?i)^(?:article|art\.?)\s+([0-9]{1,4}(?:-[0-9]{1,4})?[A-Za-z]?)\b"
)
_TITLE_NUM = re.compile(r"^([0-9]{1,4}[A-Za-z]?)\s*[.)]\s+\S")
_TITLE_LOI = re.compile(
    r"(?i)^article\s+([0-9]{1,4})\b"
    r"(?:\s*,\s*[^,\n]{1,16})*"
    r"\s+de\s+(?:la\s+|l['’])?"
    r"((?:loi|ordonnance)\b.+?)"
    r"\.?\s*$"
)
_INSTRUMENT_WORD = re.compile(
    r"(?i)\b(?:code|loi|ordonnance|ordinance|act|treaty|gesetz|constitution|statute|reglement|règlement)\b"
)
_ROMAN = re.compile(r"(?i)^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
_HEADING_KIND = {
    "partie": "part",
    "part": "part",
    "livre": "book",
    "titre": "title",
    "titulo": "title",
    "título": "title",
    "chapitre": "chapter",
    "chapter": "chapter",
    "section": "section",
}


def recover_placement(title: str, text: str) -> dict[str, str]:
    """Read a code name and headings that the record did not already file.

    Only a heading line near the start of the text is used. A sentence that
    mentions another article is left alone.
    """

    found: dict[str, str] = {}
    label = title.strip()
    loi = _TITLE_LOI.match(label)
    if loi:
        found["article"] = loi.group(1)
        found["instrument"] = loi.group(2).strip(" .")
    elif _TITLE_ARTICLE.match(label) and len(label) < 80:
        found["article"] = _TITLE_ARTICLE.match(label).group(1)  # type: ignore[union-attr]
    elif (section := _TITLE_SECTION.match(label)) is not None:
        found["section"] = section.group(1)
    elif (numbered := _TITLE_NUM.match(label)) is not None:
        found["section"] = numbered.group(1)
    lines = [item.strip() for item in text.splitlines() if item.strip()][:25]
    for index, line in enumerate(lines):
        if index == 0 and "instrument" not in found:
            named = _TITLE_LOI.match(line)
            if named:
                found.setdefault("article", named.group(1))
                found["instrument"] = named.group(2).strip(" .")
                continue
        if "instrument" not in found and _instrument_line(line):
            found["instrument"] = line
            continue
        heading = _HEADING_LINE.match(line)
        if heading:
            kind = _HEADING_KIND[heading.group(1).casefold()]
            number = heading.group(2)
            number = number if number.isdigit() else number.upper()
            if not number.isdigit() and _ROMAN.fullmatch(number) is None:
                continue
            found.setdefault(kind, number)
            continue
        article = _ARTICLE_DOT.match(line) or _ARTICLE_ONLY.match(line)
        if article:
            found.setdefault("article", re.sub(r"\s+", "", article.group(1)))
            continue
        section_line = _SECTION_ONLY.match(line)
        if section_line:
            found.setdefault("section", section_line.group(1))
    return found


def _instrument_line(line: str) -> bool:
    if len(line) < 8 or len(line) > 160:
        return False
    if (
        _HEADING_LINE.match(line)
        or _ARTICLE_DOT.match(line)
        or _ARTICLE_ONLY.match(line)
        or _SECTION_ONLY.match(line)
    ):
        return False
    letters = [char for char in line if char.isalpha()]
    if len(letters) < 6:
        return False
    if sum(char.isupper() for char in letters) / len(letters) < 0.75:
        return False
    return _INSTRUMENT_WORD.search(line) is not None


def _generic_instrument(title: str) -> bool:
    folded = _fold(title)
    if not folded:
        return True
    if folded in {"article", "section", "chapter", "chapitre", "titel", "title", "artikel"}:
        return True
    if re.match(r"(?i)^(article|art\.?|section|sec\.?)\b", title.strip()):
        return True
    if re.match(r"^[0-9]{1,4}[A-Za-z]?\s*[.)]\s+", title.strip()):
        return True
    return False


def _weak_instrument(entry: DirectoryEntry) -> bool:
    return _generic_instrument(entry.instrument) or _fold(entry.instrument) == _fold(
        _country_label(entry.jurisdiction)
    )


def _entry(record: Mapping[str, object]) -> DirectoryEntry | None:
    provenance = _provenance(record.get("provenance"))
    if provenance is None:
        return None
    locators = {name: _text(provenance.get(name)) for name in _LOCATORS}
    raw_title = _text(record.get("title"))
    recovered: dict[str, str] = {}
    if _generic_instrument(raw_title) or not any(locators.values()):
        recovered = recover_placement(raw_title, _text(record.get("text")))
    for name in _LOCATORS:
        if not locators[name]:
            locators[name] = recovered.get(name, "")
    book = _text(provenance.get("book")) or recovered.get("book", "")
    if not any(locators.values()) and not book:
        return None
    jurisdiction = _text(record.get("jurisdiction")).upper()
    if _generic_instrument(raw_title):
        instrument = recovered.get("instrument") or _country_label(jurisdiction)
    else:
        instrument = raw_title
    placed = {**locators, "book": book}
    citation, form = _citation(
        jurisdiction=jurisdiction,
        instrument=instrument,
        locators=placed,
        existing=_text(record.get("bluebook_citation")),
    )
    return DirectoryEntry(
        jurisdiction=jurisdiction,
        instrument=instrument,
        title=locators["title"],
        book=book,
        chapter=locators["chapter"],
        part=locators["part"],
        article=locators["article"],
        section=locators["section"],
        citation=citation,
        citation_form=form,
        path=_path(instrument, placed),
        entry_cid=_text(record.get("entry_cid")),
    )


def _citation(
    *,
    jurisdiction: str,
    instrument: str,
    locators: Mapping[str, str],
    existing: str,
) -> tuple[str, str]:
    if existing:
        return existing, "bluebook"
    form = _known_form(jurisdiction, instrument)
    if form is not None:
        abbreviation, pin = form
        number = locators.get(pin) or ""
        if not number and pin == "article":
            number = locators.get("section") or ""
        if not number and pin == "section":
            number = locators.get("article") or ""
        if number:
            if abbreviation in _TITLE_PREFIX and locators.get("title"):
                return f"{locators['title']} {abbreviation} § {number}", "bluebook"
            if abbreviation not in _TITLE_PREFIX:
                joiner = "art." if pin == "article" else "§"
                return f"{abbreviation} {joiner} {number}", "bluebook"
    eu = _EU_ACT.search(instrument)
    if jurisdiction == "EU" and eu is not None:
        kind = eu.group(1).casefold()
        number = eu.group(2).upper().replace("(EU) ", "")
        pin = locators.get("article") or locators.get("section")
        if pin:
            label = {"regulation": "Regulation", "directive": "Directive", "decision": "Decision"}[kind]
            token = "art." if locators.get("article") else "§"
            return f"{label} (EU) {number}, {token} {pin}", "bluebook_analog"
    return _analog(jurisdiction, instrument, locators), "bluebook_analog"


def _analog(jurisdiction: str, instrument: str, locators: Mapping[str, str]) -> str:
    pieces = [_country_label(jurisdiction)]
    if _fold(instrument) != _fold(pieces[0]):
        pieces.append(instrument)
    pins = _pins(locators)
    if pins:
        pieces.append(pins)
    return ", ".join(pieces)


def _pins(locators: Mapping[str, str]) -> str:
    labels = (
        ("part", "pt."),
        ("book", "bk."),
        ("title", "tit."),
        ("chapter", "ch."),
        ("section", "§"),
        ("article", "art."),
    )
    article = locators.get("article") or ""
    parts: list[str] = []
    for name, label in labels:
        number = locators.get(name) or ""
        if not number:
            continue
        if name == "section" and number == article:
            continue
        parts.append(f"{label} {number}")
    return ", ".join(parts)


def _known_form(jurisdiction: str, instrument: str) -> tuple[str, str] | None:
    folded = _fold(instrument)
    for code, name, abbreviation, pin in _CODE_FORMS:
        if jurisdiction == code and (folded == name or folded.startswith(name + " ")):
            return abbreviation, pin
    return None


def _path(instrument: str, locators: Mapping[str, str]) -> str:
    labels = {
        "part": "Part",
        "book": "Book",
        "title": "Title",
        "chapter": "Chapter",
        "section": "Section",
        "article": "Article",
    }
    parts = [instrument]
    article = locators.get("article") or ""
    for name in ("part", "book", "title", "chapter", "section", "article"):
        number = locators.get(name) or ""
        if not number:
            continue
        if name == "section" and number == article:
            continue
        parts.append(f"{labels[name]} {number}")
    return " / ".join(parts)


def _note_number(numbers: dict[tuple[str, ...], tuple[str, set[int]]], entry: DirectoryEntry) -> None:
    if _weak_instrument(entry):
        return
    leaf = entry.article or entry.section
    if _NUMBER.fullmatch(leaf) is None:
        return
    kind = "article" if entry.article else "section"
    key = (
        entry.jurisdiction,
        _fold(entry.instrument),
        entry.part,
        entry.book,
        entry.title,
        entry.chapter,
        kind,
    )
    slot = numbers.get(key)
    if slot is None:
        slot = (entry.instrument, set())
        numbers[key] = slot
    slot[1].add(int(leaf))


def _gaps(numbers: Mapping[tuple[str, ...], tuple[str, set[int]]]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for key, (instrument, present) in numbers.items():
        if len(present) < _GAP_MIN_PRESENT:
            continue
        start, stop = min(present), max(present)
        span = stop - start + 1
        if span > _GAP_MAX_SPAN or len(present) / span < _GAP_MIN_DENSITY:
            continue
        missing = [number for number in range(start, stop + 1) if number not in present]
        if not missing:
            continue
        jurisdiction, _folded, part, book, title, chapter, kind = key
        found.append(
            {
                "jurisdiction": jurisdiction,
                "instrument": instrument,
                "part": part,
                "book": book,
                "title": title,
                "chapter": chapter,
                "unit": kind,
                "missing": missing,
            }
        )
    found.sort(key=lambda row: (str(row["instrument"]), str(row["title"]), str(row["chapter"])))
    return found


def _unplaced(record: Mapping[str, object]) -> dict[str, str]:
    return {
        "entry_cid": _text(record.get("entry_cid")),
        "jurisdiction": _text(record.get("jurisdiction")),
        "instrument": _text(record.get("title")),
        "reason": "no_locator",
    }


def _entry_key(entry: DirectoryEntry) -> tuple[str, ...]:
    return (
        entry.jurisdiction,
        _fold(entry.instrument),
        entry.part,
        entry.book,
        entry.title,
        entry.chapter,
        entry.article,
        entry.section,
    )


def _sort_key(entry: DirectoryEntry) -> tuple[object, ...]:
    return (
        entry.jurisdiction,
        _fold(entry.instrument),
        _number_key(entry.part),
        _number_key(entry.book),
        _number_key(entry.title),
        _number_key(entry.chapter),
        _number_key(entry.article or entry.section),
        entry.entry_cid,
    )


def _number_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)


def _country_label(code: str) -> str:
    if code in _LABELS:
        return _LABELS[code]
    return _DEFAULT_NAMES.get(code) or code


def _provenance(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(loaded, dict):
            return loaded
    return None


def _fold(value: str) -> str:
    normal = unicodedata.normalize("NFKD", value).casefold()
    letters = "".join(char for char in normal if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", letters).strip()


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _parquet_rows(parts: list[Path]) -> list[tuple[Path, int]]:
    import pyarrow.parquet as pq

    return [(path, pq.ParquetFile(path).metadata.num_rows) for path in parts]


def _iter_records(parts: list[Path]) -> Iterable[dict[str, object]]:
    import pyarrow.parquet as pq

    wanted = {
        "jurisdiction",
        "admin_level",
        "instrument_type",
        "citation",
        "bluebook_citation",
        "title",
        "text",
        "content_sha256",
        "entry_cid",
        "provenance",
    }
    columns = [name for name in LEGAL_RECORD_FIELDS if name in wanted]
    for path in parts:
        present = [name for name in columns if name in pq.read_schema(path).names]
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=256, columns=present):
            yield from batch.to_pylist()


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
