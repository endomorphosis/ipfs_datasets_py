"""Admit endomorphosis country-law rows that can fill a national gap.

``world_national_law`` stays thin for some countries while
``endomorphosis/ipfs_<slug>_laws`` already holds the statute text. A fill
may copy only a row that is still a queryable law after cleaning. Metadata
cards, website pages, newsletters, chrome, chapter captions, label tables,
municipal and other sub-national corpora, and the excluded national harvests
are refused. A shared
numeric document id is not a citation. One leading article or section heading
is copied onto the locator so the row can be queried. A heading that is still
empty is filled from the source hierarchy, the record title, or an article or
section number in the source URL. The scraped site is stored with that
heading and is not used as a number. This module does not download, does not
upload, and does not rewrite statute text.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    national_slug,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
    EXCLUDED_SLUGS,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
    assign_heading,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    normalize_legal_text,
    segment_exclusive,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
    render_atomic,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    LEGAL_RECORD_FIELDS,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
    sha256_text,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.document_role import (
    classify_document_role,
)

THIN_NATIONAL_DOCS = 10
FILL_NORMALIZER = "country-source-admit/v1"
_MAX_FILL_BYTES = 64 * 1024 * 1024
_NON_NATIONAL_MARKERS = ("_municipal", "_provincial", "_governorate", "_local")
_FILL_COLUMNS = (
    "id",
    "cid",
    "entry_cid",
    "title",
    "instrument_title",
    "text",
    "body",
    "language",
    "jurisdiction",
    "country",
    "source_url",
    "article_number",
    "section_number",
    "chapter_number",
    "part_number",
    "title_number",
    "hierarchy_kind",
    "hierarchy_path",
    "official_identifier",
    "official_citation",
    "source_type",
    "collector",
    "metadata_json",
    "doc_type",
    "source_official",
    "source_policy",
    "source_revision",
)
_LOCATORS = ("title", "chapter", "part", "article", "section")
_STRUCTURAL = frozenset({"title", "chapter", "part", "article", "section"})
_PROVISION_NUMBER = re.compile(
    r"(?i)^(?:art(?:icle)?\.?|neni|nen|član|clan|section|sec\.?|paragraph|§|มาตรา)?\s*"
    r"([0-9]{1,5}|[IVXLCDM]{1,8})\.?$"
)
_CAPTION_HEADING = re.compile(
    r"(?i)^(cap[ií]tulo|chapter|titre|title|t[ií]tulo|secci[oó]n|section|part(?:ie)?|teil)\b"
)
_SENTENCE_END = re.compile(r"[.!?。؟](?:\s|$)")
_LEADING_ARTICLE = re.compile(
    r"(?i)^(?:article|art\.?|neni|section|sec\.?)\s*([0-9]{1,5})\b"
)
_DROP_POLICIES = frozenset({
    "archived_robots_disallowed",
    "noarchive_meta",
    "noindex_meta",
    "robots_unreachable",
})
_NOTICE_RE = re.compile(
    r"(?i)(\bnewsletter\b|\bblog\b|press release|communiqu[eé]|"
    r"\bnews item\b|\bnotice board\b|^lista\s+\d)"
)
_CITATION_MARK = re.compile(
    r"(?i)\b(?:nr|no|act|law|ordinance|gazette|loi|legge|gesetz|decree|code)\b"
)
_NOTICE_TYPES = frozenset({
    "newsletter",
    "blog",
    "press",
    "press_release",
    "notice",
})
_STATUTORY = re.compile(
    r"(?i)\b(?:shall|hereby|s'applique|gilt|enacted|pursuant)\b|يجب|بموجب"
)
_MIN_PROVISION = 40


@dataclass(frozen=True)
class SourceAdmission:
    admitted: bool
    reason: str
    records: tuple[dict[str, object], ...]


def admit_source_law(
    row: Mapping[str, object],
    *,
    source_dataset: str,
    source_revision: str,
) -> SourceAdmission:
    """Return queryable legal-record atoms, or a refusal with no text."""

    slug = _slug(source_dataset)
    if slug in EXCLUDED_SLUGS or _jurisdiction_slug(row) in EXCLUDED_SLUGS:
        return _refuse("excluded")
    if _non_national(slug):
        return _refuse("not_national")
    policy = row.get("source_policy")
    if isinstance(policy, str) and policy in _DROP_POLICIES:
        return _refuse("source_policy")
    if row.get("source_official") is False:
        return _refuse("unofficial")
    raw_text = row.get("text") if isinstance(row.get("text"), str) else row.get("body")
    cleaned = normalize_legal_text(raw_text if isinstance(raw_text, str) else "")
    if not cleaned:
        return _refuse("empty")
    meta = _metadata(row.get("metadata_json"))
    document_type = str(meta.get("document_type") or row.get("doc_type") or "")
    title = _string(row.get("title"))
    if _NOTICE_RE.search(title) or document_type.strip().casefold() in _NOTICE_TYPES:
        return _refuse("notice")
    language = _string(row.get("language"))
    source_url = _string(row.get("source_url"))
    labeled = {
        "title": title,
        "language": language,
        "source_url": source_url,
        "doc_type": document_type,
    }
    raw_role, _raw_reason = classify_document_role(
        {**labeled, "text": raw_text if isinstance(raw_text, str) else cleaned}
    )
    if raw_role != "law":
        return _refuse(raw_role)
    role, _reason = classify_document_role({**labeled, "text": cleaned})
    if role != "law":
        return _refuse(role)
    if not _provision_prose(cleaned):
        return _refuse("not_queryable")
    citation = _record_citation(row)
    jurisdiction = _jurisdiction_code(row)
    record = {
        "entry_cid": _string(row.get("id")) or _string(row.get("cid")),
        "title": title,
        "text": cleaned,
        "language": language,
        "jurisdiction": jurisdiction,
        "citation": citation or None,
        "source_url": source_url or None,
        "instrument_type": "statute",
        "source_repo": source_dataset,
        "source_revision": source_revision,
        "provenance": {},
    }
    atoms = tuple(expand_legal_record(record))
    kept = tuple(atom for atom in atoms if _law_atom(atom))
    if not kept:
        return _refuse("not_queryable")
    stamped = tuple(_with_leading_heading(atom, language) for atom in kept)
    if not _queryable(stamped, cleaned, citation):
        return _refuse("not_queryable")
    placed = tuple(_with_assigned_heading(atom, row) for atom in stamped)
    return SourceAdmission(True, "law", placed)


def fill_source_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    source_dataset: str,
    source_revision: str,
) -> dict[str, object]:
    """Admit a local batch. Refused rows contribute a reason and no text."""

    admitted: list[dict[str, object]] = []
    reasons: Counter[str] = Counter()
    for row in rows:
        decision = admit_source_law(
            row,
            source_dataset=source_dataset,
            source_revision=source_revision,
        )
        reasons[decision.reason] += 1
        if decision.admitted:
            admitted.extend(decision.records)
    return {
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "admitted": admitted,
        "reasons": dict(reasons),
    }


def national_gap_plan(card_docs: Mapping[str, int]) -> list[dict[str, object]]:
    """Name the country dataset that can fill a thin national card.

    A card with more than 10 documents is not a gap. Belgium, Portugal,
    Lithuania, and Ghana are listed as skipped. Nothing is downloaded.
    """

    plan: list[dict[str, object]] = []
    for code, docs in sorted(card_docs.items()):
        if not isinstance(docs, int):
            continue
        token = str(code or "").strip().upper()
        slug = national_slug(token) if token else None
        if docs > THIN_NATIONAL_DOCS or not slug:
            continue
        source = f"endomorphosis/ipfs_{slug}_laws"
        if slug in EXCLUDED_SLUGS:
            plan.append(
                {
                    "code": token,
                    "slug": slug,
                    "source_dataset": source,
                    "card_docs": docs,
                    "action": "skip",
                    "reason": "excluded",
                }
            )
            continue
        plan.append(
            {
                "code": token,
                "slug": slug,
                "source_dataset": source,
                "card_docs": docs,
                "action": "fill",
                "reason": "thin_docs",
            }
        )
    return plan


def fill_country_parquet(
    source_path: Path | str,
    dest_dir: Path | str,
    *,
    source_dataset: str,
    source_revision: str,
) -> dict[str, object]:
    """Write admitted legal-record rows from one local country parquet.

    The file must already be on disk. A municipal corpus, an excluded
    national harvest, or a file over 64 MiB is refused before any row is
    read. Refused rows are counted and their text is not written.
    """

    return fill_country_corpus(
        [source_path],
        dest_dir,
        source_dataset=source_dataset,
        source_revision=source_revision,
        flush_atoms=10**12,
    )


def fill_country_corpus(
    source_paths: Iterable[Path | str],
    dest_dir: Path | str,
    *,
    source_dataset: str,
    source_revision: str,
    flush_atoms: int = 8192,
) -> dict[str, object]:
    """Admit every local corpus part into queryable legal-record shards.

    Files must already be on disk. An excluded harvest, a municipal or
    other sub-national corpus, a missing file, or a part over 64 MiB is
    refused before any row is read. Atoms are written in numbered parts so
    a whole country is not held in memory. Refused rows are counted and
    their text is not written. This function does not download or upload.
    """

    slug = _slug(source_dataset)
    if slug in EXCLUDED_SLUGS:
        raise ValueError("excluded")
    if _non_national(slug):
        raise ValueError("not_national")
    if not _is_sha(source_revision):
        raise ValueError("source_revision")
    if flush_atoms < 1:
        raise ValueError("flush_atoms")
    sources = [Path(path) for path in source_paths]
    if not sources:
        raise ValueError("source")
    total_bytes = 0
    for source in sources:
        if not source.is_file():
            raise ValueError("source")
        size = source.stat().st_size
        if size > _MAX_FILL_BYTES:
            raise ValueError("source")
        total_bytes += size
    destination = Path(dest_dir) / slug
    destination.mkdir(parents=True, exist_ok=True)
    stale_report = destination / "report.json"
    if stale_report.exists():
        stale_report.unlink()
    for stale in destination.glob("part-*.parquet"):
        stale.unlink()
    reasons: Counter[str] = Counter()
    revisions: set[str] = set()
    rows_read = 0
    located = 0
    atoms_written = 0
    pending: list[dict[str, str | None]] = []
    written: list[str] = []

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        written.append(_write_fill_part(destination, len(written), pending))
        pending = []

    for source in sources:
        for revision, decision in _iter_source_decisions(
            source,
            source_dataset=source_dataset,
            source_revision=source_revision,
        ):
            rows_read += 1
            if isinstance(revision, str):
                revisions.add(revision)
            reasons[decision.reason] += 1
            if not decision.admitted:
                continue
            for atom in decision.records:
                pending.append(_encode_fill_atom(atom))
                provenance = atom.get("provenance")
                if isinstance(provenance, dict) and _located(provenance):
                    located += 1
                atoms_written += 1
                if len(pending) >= flush_atoms:
                    flush()
    flush()
    report = {
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "source_path": str(sources[0]),
        "source_files": [path.name for path in sources],
        "source_bytes": total_bytes,
        "slug": slug,
        "rows_read": rows_read,
        "atoms_written": atoms_written,
        "atoms_with_locator": located,
        "revisions": sorted(revisions),
        "reasons": dict(reasons),
        "coverage": "snapshot" if atoms_written else "not_published",
        "corpus_complete": True,
        "normalizer_version": FILL_NORMALIZER,
        "files": written,
    }
    (destination / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _fill_row(row: Mapping[str, object]) -> dict[str, object]:
    instrument = _cell(row, "instrument_title")
    title = row.get("title") if isinstance(row.get("title"), str) else instrument
    text = row.get("text") if isinstance(row.get("text"), str) else row.get("body")
    entry = row.get("id") if isinstance(row.get("id"), str) else row.get("entry_cid")
    if not isinstance(entry, str):
        entry = row.get("cid")
    filled = {
        "id": entry if isinstance(entry, str) else "",
        "title": title if isinstance(title, str) else "",
        "instrument_title": instrument,
        "text": text if isinstance(text, str) else "",
        "language": _cell(row, "language"),
        "jurisdiction": _cell(row, "jurisdiction"),
        "country": _cell(row, "country"),
        "source_url": _cell(row, "source_url"),
        "article_number": _cell(row, "article_number"),
        "section_number": _cell(row, "section_number"),
        "chapter_number": _cell(row, "chapter_number"),
        "part_number": _cell(row, "part_number"),
        "title_number": _cell(row, "title_number"),
        "hierarchy_kind": _cell(row, "hierarchy_kind"),
        "hierarchy_path": _cell(row, "hierarchy_path"),
        "official_identifier": _cell(row, "official_identifier"),
        "official_citation": _cell(row, "official_citation"),
        "source_type": _cell(row, "source_type"),
        "collector": _cell(row, "collector"),
        "metadata_json": _cell(row, "metadata_json"),
        "doc_type": _cell(row, "doc_type"),
        "source_official": row.get("source_official"),
        "source_policy": row.get("source_policy"),
    }
    return filled


def _encode_fill_atom(atom: Mapping[str, object]) -> dict[str, str | None]:
    provenance = atom.get("provenance")
    copied = dict(provenance) if isinstance(provenance, dict) else {}
    record: dict[str, object] = {field: None for field in LEGAL_RECORD_FIELDS}
    record.update(
        {
            "jurisdiction": atom.get("jurisdiction"),
            "admin_level": "country",
            "instrument_type": "statute",
            "citation": atom.get("citation"),
            "title": atom.get("title"),
            "text": atom.get("text"),
            "language": atom.get("language"),
            "source_url": atom.get("source_url"),
            "content_sha256": atom.get("content_sha256")
            or sha256_text(atom.get("text") if isinstance(atom.get("text"), str) else None),
            "scraper_id": "country_laws_ir",
            "normalizer_version": FILL_NORMALIZER,
            "source_repo": atom.get("source_repo"),
            "source_revision": atom.get("source_revision"),
            "entry_cid": atom.get("entry_cid"),
            "provenance": copied,
        }
    )
    copied["jsonld"] = render_atomic(record, "jsonld")
    encoded: dict[str, str | None] = {}
    for field in LEGAL_RECORD_FIELDS:
        value = record.get(field)
        if field == "provenance":
            encoded[field] = json.dumps(copied, sort_keys=True, ensure_ascii=False)
        elif value is None:
            encoded[field] = None
        else:
            encoded[field] = str(value)
    return encoded


def _fill_schema():
    import pyarrow as pa

    return pa.schema([pa.field(name, pa.string()) for name in LEGAL_RECORD_FIELDS])


def _is_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value)
    )


def _refuse(reason: str) -> SourceAdmission:
    return SourceAdmission(False, reason, ())


def _iter_source_decisions(
    source: Path,
    *,
    source_dataset: str,
    source_revision: str,
):
    import pyarrow.parquet as pq

    columns = [name for name in _FILL_COLUMNS if name in pq.read_schema(source).names]
    parquet = pq.ParquetFile(source)
    for batch in parquet.iter_batches(batch_size=256, columns=columns):
        for row in batch.to_pylist():
            row_revision = row.get("source_revision")
            revision = row_revision if _is_sha(row_revision) else source_revision
            decision = admit_source_law(
                _fill_row(row),
                source_dataset=source_dataset,
                source_revision=revision,
            )
            yield revision, decision


def _write_fill_part(
    destination: Path,
    part_index: int,
    encoded: list[dict[str, str | None]],
) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq

    part = destination / f"part-{part_index:06d}.parquet"
    table = pa.Table.from_pylist(encoded, schema=_fill_schema())
    pq.write_table(table, part, compression="zstd")
    return str(part)


def _non_national(slug: str) -> bool:
    return (not slug) or any(marker in slug for marker in _NON_NATIONAL_MARKERS)


def _slug(source_dataset: str) -> str:
    name = str(source_dataset or "").strip()
    if name.startswith("endomorphosis/"):
        name = name.split("/", 1)[1]
    if name.startswith("ipfs_") and name.endswith("_laws"):
        return name[len("ipfs_") : -len("_laws")]
    return ""


def _jurisdiction_slug(row: Mapping[str, object]) -> str:
    resolved = resolve_jurisdiction(_string(row.get("jurisdiction")) or _string(row.get("country")))
    if resolved is None or resolved.admin_level != "country" or not resolved.slug:
        return ""
    return resolved.slug


def _jurisdiction_code(row: Mapping[str, object]) -> str | None:
    resolved = resolve_jurisdiction(_string(row.get("jurisdiction")) or _string(row.get("country")))
    if resolved is None or resolved.admin_level != "country":
        return None
    return resolved.code


def _metadata(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def _string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _cell(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _with_assigned_heading(
    atom: dict[str, object],
    row: Mapping[str, object],
) -> dict[str, object]:
    """Fill an empty locator. A heading the splitter already set is left as it is."""

    provenance = atom.get("provenance")
    if not isinstance(provenance, dict) or _located(provenance):
        return atom
    statute = provenance.get("statute")
    assignment = assign_heading(
        {
            "title": atom.get("title"),
            "text": atom.get("text"),
            "citation": atom.get("citation"),
            "statute": statute if isinstance(statute, str) else "",
            "source_url": atom.get("source_url"),
            "hierarchy_kind": row.get("hierarchy_kind"),
            "hierarchy_path": row.get("hierarchy_path") or provenance.get("hierarchy_path"),
            "section_number": row.get("section_number"),
            "article_number": row.get("article_number"),
            "chapter_number": row.get("chapter_number"),
            "part_number": row.get("part_number"),
            "title_number": row.get("title_number"),
            "instrument_title": row.get("instrument_title"),
            "official_citation": row.get("official_citation"),
            "official_identifier": row.get("official_identifier"),
            "source_type": row.get("source_type"),
            "collector": row.get("collector"),
        }
    )
    for key, value in assignment.locators:
        current = provenance.get(key)
        if not (isinstance(current, str) and current.strip()):
            provenance[key] = value
    if assignment.hierarchy_path:
        path = provenance.get("hierarchy_path")
        if not (isinstance(path, str) and path.strip()):
            provenance["hierarchy_path"] = assignment.hierarchy_path
    provenance["heading_status"] = assignment.status
    provenance["heading_evidence"] = assignment.evidence
    if assignment.site:
        provenance["heading_site"] = assignment.site
        provenance["heading_site_from"] = assignment.site_from
    if assignment.instrument:
        provenance["heading_instrument"] = assignment.instrument
    return atom


def _provision_number(value: object) -> str:
    """Article, section, or paragraph number. A chapter label is not one."""

    match = _PROVISION_NUMBER.match(_string(value))
    if match is None:
        return ""
    return match.group(1)


def _record_citation(row: Mapping[str, object]) -> str:
    """Instrument citation, or the provision number when the id is only digits.

    Country rows store a shared document number in ``official_identifier``.
    That number is the same on every article, so it is not a provision citation.
    """

    official = _string(row.get("official_identifier"))
    number = _provision_number(row.get("article_number"))
    title = _string(row.get("title"))
    if (
        official
        and official != title
        and not official.isdigit()
        and re.search(r"\d", official)
        and _CITATION_MARK.search(official)
    ):
        return official
    return number


def _provision_prose(text: str) -> bool:
    """True when the cleaned row is a provision, not a caption or a label table."""

    if _caption_shell(text):
        return False
    if _STATUTORY.search(text):
        return True
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _CAPTION_HEADING.match(line):
            continue
        words = re.findall(r"[^\W\d_]{2,}", line)
        if len(words) >= 8 and _SENTENCE_END.search(line):
            return True
        letters = re.findall(r"[^\W\d_]", line)
        if len(letters) >= 40:
            return True
    return False


def _caption_shell(text: str) -> bool:
    """A chapter or title line plus a label, with no provision sentence."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > 4 or not _CAPTION_HEADING.match(lines[0]):
        return False
    if _STATUTORY.search(text):
        return False
    for line in lines:
        words = re.findall(r"[^\W\d_]{2,}", line)
        if len(words) >= 8 and _SENTENCE_END.search(line):
            return False
    return True


def _with_leading_heading(atom: dict[str, object], language: str) -> dict[str, object]:
    """Copy one leading article or section number onto the unsplit atom."""

    provenance = atom.get("provenance")
    text = atom.get("text")
    if not isinstance(provenance, dict) or not isinstance(text, str):
        return atom
    if _located(provenance):
        return atom
    leading = _LEADING_ARTICLE.match(text.lstrip())
    if leading is not None:
        number = leading.group(1)
        provenance["article"] = number
        provenance.setdefault("section", number)
        provenance.setdefault("hierarchy_path", f"Article {number}")
        statute = provenance.get("statute")
        if not isinstance(statute, str) or not statute.strip():
            provenance["statute"] = number
        return atom
    units = [
        unit
        for unit in segment_exclusive(text, language=language)
        if unit.kind in _STRUCTURAL and unit.number and len(unit.body.strip()) >= 16
    ]
    if not units:
        return atom
    numbers = {unit.number for unit in units}
    if len(numbers) != 1:
        return atom
    lead = min(units, key=lambda unit: unit.char_start)
    if lead.char_start > 80:
        return atom
    number = lead.number
    kind = "article" if any(unit.kind == "article" for unit in units) else lead.kind
    if kind == "article":
        provenance["article"] = number
        provenance.setdefault("section", number)
    elif kind == "section":
        provenance.setdefault("section", number)
    elif kind in {"chapter", "part", "title"}:
        provenance.setdefault(kind, number)
    else:
        return atom
    if lead.hierarchy_path:
        provenance.setdefault("hierarchy_path", lead.hierarchy_path)
    statute = provenance.get("statute")
    if not isinstance(statute, str) or not statute.strip():
        provenance["statute"] = number
    return atom


def _located(provenance: Mapping[str, object]) -> bool:
    for key in _LOCATORS:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _law_atom(atom: Mapping[str, object]) -> bool:
    text = atom.get("text")
    provenance = atom.get("provenance")
    if not isinstance(text, str) or not text.strip():
        return False
    if not isinstance(provenance, dict):
        return False
    return provenance.get("document_role") == "law"


def _queryable(
    atoms: tuple[dict[str, object], ...],
    cleaned: str,
    citation: str,
) -> bool:
    if any(_has_locator(atom) for atom in atoms):
        return True
    if len(cleaned) >= _MIN_PROVISION and _STATUTORY.search(cleaned):
        return True
    return bool(citation) and len(cleaned) >= _MIN_PROVISION


def _has_locator(atom: Mapping[str, object]) -> bool:
    provenance = atom.get("provenance")
    if not isinstance(provenance, dict):
        return False
    for key in _LOCATORS:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            return True
    path = provenance.get("hierarchy_path")
    return isinstance(path, str) and any(
        label in path for label in ("Title ", "Chapter ", "Part ", "Article ", "Section ")
    )
