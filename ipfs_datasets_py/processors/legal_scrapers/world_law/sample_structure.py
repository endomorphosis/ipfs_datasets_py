"""Sample cleaned legal rows and report structure without admitting parsers.

The report counts law, metadata, and informative rows. Locator counts for a
law atom include title, chapter, part, article, statute, section, and
subsection. A line that still looks like a heading is listed as a candidate.
Candidates are not written into the heading lexicon.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.document_role import (
    classify_document_role,
)

_LOCATORS = (
    "title",
    "chapter",
    "part",
    "article",
    "statute",
    "section",
    "subsection",
    "hierarchy_path",
)
_PATH_LABELS = (
    ("Title ", "title"),
    ("Chapter ", "chapter"),
    ("Part ", "part"),
    ("Article ", "article"),
    ("Section ", "section"),
)
_MAX_PARQUET_BYTES = 8 * 1024 * 1024
_WORD_NUM = re.compile(
    r"^(?P<word>[^\W\d_][\w'’.\-]{1,40})\s+(?P<num>[0-9]{1,4}|[IVXLCDM]{1,8})\b",
    re.UNICODE,
)
_NUMBERED = re.compile(r"^(?P<num>[0-9]{1,3})\.\s+(?P<rest>\S.{2,70})$")
_MONTHS = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "janvier", "février", "fevrier", "mars", "avril", "mai", "juin", "juillet",
    "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre",
    "januar", "februar", "märz", "marz", "mai", "juni", "juli", "oktober",
    "dezember",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
})
_STOP = frozenset({
    "the", "this", "that", "and", "for", "from", "with", "under", "between",
    "les", "des", "der", "die", "das", "und", "von", "para", "por", "con",
})


def sample_records(
    records: Iterable[Mapping[str, object]],
    *,
    limit: int = 60,
) -> dict[str, object]:
    """Classify and expand up to ``limit`` records.

    ``limit`` below 1 reads nothing. The function does not download, upload,
    or edit a parser.
    """

    if limit < 1:
        rows: list[Mapping[str, object]] = []
    else:
        rows = []
        for record in records:
            rows.append(record)
            if len(rows) >= limit:
                break
    roles = Counter({"law": 0, "metadata": 0, "informative": 0})
    locator_atoms = Counter({key: 0 for key in _LOCATORS})
    candidates: Counter[tuple[str, str]] = Counter()
    law_atoms = 0
    empty_after_clean = 0
    for record in rows:
        atoms = expand_legal_record(dict(record))
        if not atoms:
            empty_after_clean += 1
            continue
        provenance = atoms[0].get("provenance")
        role = provenance.get("document_role") if isinstance(provenance, dict) else None
        if role not in roles:
            role, _reason = classify_document_role(record)
        roles[str(role)] += 1
        if role != "law":
            continue
        for atom in atoms:
            law_atoms += 1
            found = _locator_keys(atom)
            for key in found:
                locator_atoms[key] += 1
            if "article" in found or "section" in found or "chapter" in found or "title" in found:
                continue
            text = atom.get("text")
            if isinstance(text, str):
                language = record.get("language")
                for kind, line in _candidates(
                    text,
                    language=language if isinstance(language, str) else "",
                ):
                    candidates[(kind, line)] += 1
    ranked = [
        {"kind": kind, "line": line, "count": count}
        for (kind, line), count in candidates.most_common(12)
    ]
    return {
        "rows": len(rows),
        "roles": {name: int(roles[name]) for name in ("law", "metadata", "informative")},
        "empty_after_clean": empty_after_clean,
        "law_atoms": law_atoms,
        "locator_atoms": {key: int(locator_atoms[key]) for key in _LOCATORS},
        "heading_candidates": ranked,
    }


def sample_parquet(path: Path, *, limit: int = 60) -> dict[str, object]:
    """Sample one local parquet shard of at most 8 MiB.

    A larger file is refused. The reader uses the ``body`` column when it
    is present, and the ``text`` column otherwise.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source.stat().st_size > _MAX_PARQUET_BYTES:
        raise ValueError(f"{source.name} exceeds 8 MiB")
    import pyarrow.parquet as pq

    frame = pq.ParquetFile(source)
    names = set(frame.schema_arrow.names)
    text_column = "body" if "body" in names else "text" if "text" in names else ""
    if not text_column:
        raise ValueError(f"{source.name} has no body or text column")
    wanted = [
        column
        for column in (
            text_column,
            "title",
            "title_native",
            "html_title",
            "language",
            "source_url",
            "doc_type",
            "instrument_type",
        )
        if column in names
    ]
    records: list[dict[str, object]] = []
    for batch in frame.iter_batches(batch_size=32, columns=wanted):
        for row in batch.to_pylist():
            text = row.get(text_column)
            records.append(
                {
                    "text": text if isinstance(text, str) else None,
                    "title": row.get("title") or row.get("title_native") or row.get("html_title"),
                    "language": row.get("language"),
                    "source_url": row.get("source_url"),
                    "doc_type": row.get("doc_type") or row.get("instrument_type"),
                    "provenance": {},
                }
            )
            if len(records) >= limit:
                return sample_records(records, limit=limit)
    return sample_records(records, limit=limit)


def _locator_keys(atom: Mapping[str, object]) -> set[str]:
    raw = atom.get("provenance")
    provenance = raw if isinstance(raw, dict) else {}
    found: set[str] = set()
    for key in _LOCATORS:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            found.add(key)
    path = provenance.get("hierarchy_path")
    if isinstance(path, str):
        for label, key in _PATH_LABELS:
            if label in path:
                found.add(key)
    return found


def _candidates(text: str, *, language: str = "") -> list[tuple[str, str]]:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.profiles import (
        HEADING_LEXICON,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        split_structured_units,
    )

    # Retrieval units already carry a locator. Internal hits that the
    # retrieval split refused stay candidates.
    covered = {
        unit.char_start
        for unit in split_structured_units(text, language=language)
        if unit.kind in {"title", "chapter", "part", "article", "section"}
    }
    found: list[tuple[str, str]] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        start = offset + (len(raw) - len(raw.lstrip()))
        offset += len(raw)
        if not line or len(line) > 80 or start in covered:
            continue
        word_match = _WORD_NUM.match(line)
        if word_match:
            word = word_match.group("word")
            folded = word.casefold().rstrip(".")
            if folded in _STOP:
                continue
            if folded in HEADING_LEXICON or folded.rstrip(".") in HEADING_LEXICON:
                found.append(("missed_lexicon", line[:80]))
                continue
        numbered = _NUMBERED.match(line)
        if numbered is None:
            continue
        rest = numbered.group("rest")
        first = rest.split(None, 1)[0].casefold().rstrip(".,")
        if first in _MONTHS:
            continue
        found.append(("numbered_caption", line[:80]))
    return found
