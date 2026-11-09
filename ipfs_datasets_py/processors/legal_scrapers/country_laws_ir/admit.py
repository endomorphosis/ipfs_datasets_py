"""Admit endomorphosis country-law rows that can fill a national gap.

``world_national_law`` stays thin for some countries while
``endomorphosis/ipfs_<slug>_laws`` already holds the statute text. A fill
may copy only a row that is still a queryable law after cleaning. Metadata
cards, website pages, newsletters, chrome, chapter captions, label tables,
municipal and other sub-national corpora, a first-level subdivision
code such as CH-BE, an instrument issued by a named municipality, a
Latvian municipal binding regulation, fee, or charter, an Andorran
instrument issued by a Comú or by the Consell de Comú, and the excluded
national harvests are refused. A statute or government regulation that
only mentions municipalities is kept, including a Cabinet regulation.
A law of the Consell General that only mentions the Comuns is kept.
A supranational code such as EU is kept with that code. A shared
numeric document id is not a citation. A title that is only a code
provision, such as ``Article L111-2`` or ``Article 8-2``, is that article
when the row stays one provision. An annex title is not. One article
or section heading is copied onto the unsplit row, including a heading
after the preamble such as ``Article únic``, ``Articolo unico.``, or
``Art. 1``. An annex label is not. An Italian repeal banner is not.
A Polish ``§ 1.`` or ``Artykuł 5`` line followed by a closed sentence is
that provision. An empty ``Art. 8.`` card, ``(uchylony)``, and
``otrzymuje brzmienie:`` are not. A trailing list marker with no item
text is not. A citation or a list that would be cut into another
section is not. A following ``Rozdział`` line or an editorial
footnote is not.
An Indonesian ``Pasal 11`` line followed by one closed provision is
that article. ``Cukup jelas``, ``Sudah jelas``, ``Dihapus``, a running
``PRESIDEN`` header, an ellipsis gap, and a following ``Bab`` are not.
A Korean ``제1조(시행일)`` line that is only the effective-date sentence
is that article. ``생략``, ``삭제``, and a following addendum are not.
A Croatian ``Članak 223.`` line followed by one closed provision is
that article. A ``Klasa`` / ``Urbroj`` signature block is not.
A Swedish ``8 §`` line that is one closed sentence is that section.
``har upphävts``, ``uppphävts``, ``utgått``, ``upphör att gälla``,
and ``ny beteckning`` are not. A lowercase continuation is not.
A Japanese statute that names its law number, such as
``明治三十五年法律第五十号``, and has no ``第N条`` line is that whole
instrument. The law number is not an article. ``削除`` and a line that
is only ``廃止`` are not. A row that stops before the sentence ends,
a ``略`` omission, a skipped paragraph number, and a commencement
clause for an article the row does not contain are not.
An Amharic ``N.`` line that is the only such heading, followed by one
closed provision, is that section. ``1)`` items stay on the section.
A citation ``አንቀጽ N`` is not an article. A second ``N.`` heading, a
row that stops before ``።`` or ``::``, a two-column page, and a line
whose words are split into single letters are not.
A Finnish or Swedish ``N §`` or ``N a §`` section keeps that number when a
later chapter line shares the row. A repeal note (``on kumottu``,
``har upphävts``) does not. A section copied into the title is still that
section.
A Chinese ``第 N 條`` line with its sentence is a provision when no
single line reaches forty letters. A row that is only ``（刪除）`` is not.
A chart note that mentions an article is not.
A heading that is still empty is filled from the source hierarchy, the
record title, or an article or
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
    ResolvedJurisdiction,
    national_slug,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
    EXCLUDED_SLUGS,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
    assign_heading,
    locators_from_code_title,
    locators_from_punkts_title,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.placement import (
    classify_placement,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    _latin_fold,
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
    korean_commencement_line,
    section_repeal_note,
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
# Czech gazette instruments often have no section heading. The enacting
# formula is the statute. The leading "12." is the collection number.
_CZECH_ENACTING = re.compile(
    r"(?i)(?:\bnařizuje\b|\busneslo se\b|\bstanoví\b|\bvyhlašuj)"
)
_CZECH_COLLECTION = re.compile(r"^\s*([0-9]{1,4})\.?\s*(?:\n|$)")
# A provision line, or the same line with the sentence continuing after it.
_ZH_ARTICLE_LINE = re.compile(
    r"^第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*(?:[-－]\s*[0-9]+\s*)?[条條]"
    r"(?:之\s*[0-9一二三四五六七八九十百千万零〇两]+)?\s*(?P<rest>.*)$"
)
_ZH_DELETE = re.compile(
    r"^[（(〈【\[]?\s*(?:刪除|删除|本條刪除|本条删除|廢止|废止)\s*[)）〉】\]]?[.。]?\s*$"
)
_EN_ARTICLE_LINE = re.compile(
    r"(?i)^(?:Article|Art\.)\s+\S+\.?\s*(?P<rest>.*)$"
)
_EN_OMIT = re.compile(
    r"(?i)^[（(\[]?\s*(?:omitted|delete|deleted|repealed)\s*[)）\]]?[.]?\s*$"
)
# A Dutch article label is the whole line. ``4:81a`` is one provision number.
# ``Vervallen`` and ``Wijzigt de Wet ...`` are shells, not the operative text.
_NL_LABEL = re.compile(
    r"(?i)^artikel\s+([0-9]+(?::[0-9]+)?[a-z]?|[IVXLCDM]{1,8})\s*$"
)
_NL_REPEAL = re.compile(
    r"(?i)^\[?\s*(?:vervallen|gereserveerd)\b"
    r"(?:\s*\.?\s*(?:dit onderdeel is nog niet inwerking getreden\.?)?)?\s*$"
)
_NL_POINTER = re.compile(r"(?i)^(?:wijzigt|bevat wijziging)\w*\b")
# A Polish label is the whole line: ``§ 1.``, ``§ 3c.``, ``Art. 8.``, ``Artykuł 5``.
# The body has to be a closed sentence. An empty card, ``(uchylony)``, and
# ``otrzymuje brzmienie:`` stay out. A trailing ``1)`` with no item text stays out.
_PL_LABEL = re.compile(
    r"(?i)^(?:§+\s*[0-9]+[a-z]?\.?|art\.\s*[0-9]+[a-z]?\.?|artykuł\s+[0-9]+[a-z]?)\s*$"
)
_PL_SHELL = re.compile(
    r"(?i)uchylon|otrzymuj|brzmienie|pokaż całość|następuje"
    r"|wprowadza się następujące zmiany"
)
_PL_DIRT = re.compile(r"[~¬\xad]|[A-Za-z]{2,}[0-9]|[0-9][A-Za-z]{2,}")
_PL_SECOND = re.compile(r"(?i)^(?:art\.?|artykuł|§+|article)\b")
_PL_CHAPTER = re.compile(r"(?i)^(?:rozdział|dział)\b")
_PL_FOOTNOTE = re.compile(r"^[0-9]{1,3}\)\S")
_PL_PAGEJUMP = re.compile(r"\d{2,}\s*/\s*\d{2,}")
_PL_MARKER = re.compile(r"(?i)^(?:[0-9]+[a-z]?|[a-z])[.)]$")
_PL_QUOTE_END = frozenset({'"', "”", "„", ".", "”.", "'"})
# An Indonesian label is the whole line: ``Pasal 11`` or ``Pasal 3M``.
# ``Cukup jelas`` is the elucidation stub. A running header, an ellipsis
# left by a page break, and a following Bab are not the article.
_ID_LABEL = re.compile(r"(?i)^pasal\s+([0-9]+[a-z]?)\s*$")
_ID_SHELL = re.compile(
    r"(?i)cukup\s+je[l1]as|sudah jelas|dihapus|tidak perlu|tidak memerlukan|"
    r"\bpenjelasan\b"
)
_ID_HEADER = re.compile(r"(?i)^(?:presiden|republik indonesia|salinan|sk\s*n[ro]\b.*)$")
_ID_NEXT = re.compile(r"(?i)^(?:bab|bagian|paragraf)\b")
_ID_LIHAT = re.compile(r"(?i)^lihat\b")
_ID_ELLIPSIS = re.compile(r"\.\s*\.\s*\.|\.\.\.")
_ID_CAMEL = re.compile(r"[a-z][A-Z]")
_ID_MARK = re.compile(r"[;]{2,}|[*#]|[A-Za-z]:[A-Za-z]")
_MIN_PROVISION = 40
_NATIONAL_LEVELS = frozenset({"country", "supranational"})
_SUBNATIONAL_LEVELS = frozenset({"adm1", "municipality"})
_NATIONAL_INSTRUMENT_TOKENS = frozenset({"zakon", "uredba", "zakonik"})
# A named municipality is the issuer: "občine Metlika", "občini Koper",
# "občinski svet". Plural "občin" with no place name is a subject, not an issuer.
_MUNICIPAL_ISSUER = re.compile(
    r"obcin[aeio](?:[ -][a-z])|obcinsk|mestne-obcine"
)
# Issuer phrases. Plural "občin" with no place name is a subject, not an issuer.
_MUNICIPAL_TEXT = re.compile(
    r"skupscin[aeio]\s+obcin[aeio]\s+[a-z]"
    r"|obcinsk(?:i|ega|em|ih|imi|a)?\s+svet"
    r"|proracuna\s+obcin[aeio]\s+[a-z]"
    r"|svet\s+obcin[aeio]\s+[a-z]"
)
# Latvian municipal issuers, matched on the instrument title. Genitive plural
# "pašvaldību" is a subject ("Noteikumi par ... pašvaldību"), not an issuer.
# "pilsētas pašvaldības" in a transfer order names the recipient.
_LATVIAN_MUNICIPAL = re.compile(
    r"saistos"
    r"|pasvaldibas\s+nodev"
    r"|pasvaldibas\s+nolikum"
    r"|pasvaldibas\s+social"
    r"|pagasta\s+(?:padomes|buvvald)"
)
_LATVIAN_NAMED = re.compile(r"(?<![a-z])([a-z]{3,}(?:as|es))\s+pasvaldibas\b")
_LATVIAN_GENERIC_NAME = frozenset({
    "pilsetas",
    "valstspilsetas",
    "novada",
    "latvijas",
    "republikas",
})
_LATVIAN_CABINET = "ministru kabineta noteikum"
# Andorran parish issuers. "El Comú d'Encamp" and "Consell de Comú" enact.
# "pel Comú" and plural "Comuns" are subjects in a Consell General law.
# A title may name the issuer as "del Comú de Sant Julià" without the
# enactment clause. That title form is not applied to the statute body.
_ANDORRAN_PARISH = re.compile(
    r"(?<![a-z])el comu d['\u2019]"
    r"|(?<![a-z])el comu de\s+[a-z]"
    r"|(?<![a-z])el consell del comu\b"
    r"|consell de comu\b"
    r"|organ contractant:\s*comu\b"
    r"|p\.?\s*o\.?\s+(?:de\s+)?l['\u2019]?hble\.?\s+comu\b"
    r"|p\.?\s*o\.?\s+del\s+comu\b"
)
_ANDORRAN_PARISH_TITLE = re.compile(
    r"del comu d['\u2019]|del comu de\s+[a-z]"
)


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
    resolved = _resolved_jurisdiction(row)
    if resolved is not None and resolved.admin_level in _SUBNATIONAL_LEVELS:
        return _refuse("not_national")
    if _municipal_instrument(row):
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
    prose = _provision_prose(cleaned)
    am_section = _am_closed_section(cleaned)
    sk_article = _sk_commencement(cleaned)
    if not prose and not am_section and not sk_article:
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
    # The shared splitter reads ``1)`` as a section and ``አንቀጽ N`` as an
    # article. On this closed Amharic provision those are items and
    # citations. Keep the cleaned row whole.
    if am_section and not prose:
        atoms = (_am_whole_section(record, cleaned, am_section),)
    elif sk_article:
        atoms = (_sk_whole_article(record, cleaned, sk_article),)
    kept = tuple(
        atom
        for atom in atoms
        if _law_atom(atom)
        and not section_repeal_note(
            atom.get("text") if isinstance(atom.get("text"), str) else ""
        )
        and not _nl_shell(
            atom.get("text") if isinstance(atom.get("text"), str) else ""
        )
    )
    if not kept:
        return _refuse("not_queryable")
    # A divided row already carries the headings the splitter found. Stamping
    # the parent title onto those pieces would file them under the wrong article.
    if len(kept) == 1:
        kept = (_with_code_title(kept[0]),)
        kept = (_with_sole_heading(kept[0], language),)
    stamped = tuple(_with_leading_heading(atom, language) for atom in kept)
    if not _queryable(stamped, cleaned, citation):
        return _refuse("not_queryable")
    placed = tuple(
        _with_japanese_whole_instrument(
            _drop_gazette_number(_with_assigned_heading(atom, row))
        )
        for atom in stamped
    )
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
            "admin_level": _fill_admin_level(atom.get("jurisdiction")),
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


def _resolved_jurisdiction(row: Mapping[str, object]) -> ResolvedJurisdiction | None:
    """Use the jurisdiction field, then the country field when that field does not resolve.

    A subdivision code such as CH-BE is kept, so the country name beside it
    cannot relabel cantonal or state law as the parent country. A country
    name such as ``Bosnia and Herzegovina`` falls through to a code such as
    ``ba`` in the country field.
    """

    jurisdiction = _string(row.get("jurisdiction"))
    resolved = resolve_jurisdiction(jurisdiction) if jurisdiction else None
    if resolved is not None:
        return resolved
    country = _string(row.get("country"))
    if not country or country == jurisdiction:
        return None
    return resolve_jurisdiction(country)


def _jurisdiction_slug(row: Mapping[str, object]) -> str:
    resolved = _resolved_jurisdiction(row)
    if resolved is None or resolved.admin_level not in _NATIONAL_LEVELS or not resolved.slug:
        return ""
    return resolved.slug


def _instrument_token(folded: str) -> str:
    """First word of the citation slug. ``zakon-o-...`` and ``Zakon o ...`` share it."""

    segment = folded.replace("\\", "/").rsplit("/", 1)[-1]
    segment = segment.split(",", 1)[0].strip()
    token = re.split(r"[\s\-–—]", segment, maxsplit=1)[0]
    return token.strip(" .:")


def _identity_text(row: Mapping[str, object]) -> str:
    for key in (
        "official_citation",
        "official_identifier",
        "source_url",
        "instrument_title",
    ):
        raw = _string(row.get(key))
        if raw.strip():
            return raw
    return ""


def _statute_text(row: Mapping[str, object]) -> str:
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return text
    body = row.get("body")
    return body if isinstance(body, str) else ""


def _latvian_municipal_title(title: str) -> bool:
    """True when a Latvian instrument title names a municipal issuer.

    The citation on these rows is a numeric id, so the instrument title is
    read even when that id is present. A Cabinet regulation stays. A place
    name directly before ``pašvaldības`` is an issuer. ``pilsētas`` and
    ``novada`` in that position name a recipient in a national order.
    """

    folded = _latin_fold(title).casefold()
    if not folded or _LATVIAN_CABINET in folded:
        return False
    if _LATVIAN_MUNICIPAL.search(folded) is not None:
        return True
    for match in _LATVIAN_NAMED.finditer(folded):
        if match.group(1) not in _LATVIAN_GENERIC_NAME:
            return True
    return False


def _andorran_parish_text(text: str, *, title: bool = False) -> bool:
    """True when an Andorran instrument is issued by a parish Comú.

    Gazette bodies store a null between letters. Cleaning runs before the
    issuer phrases are read. ``El Comú d'Encamp`` and ``Consell de Comú``
    are issuers. ``pel Comú`` and plural ``Comuns`` name a subject in a
    Consell General law. The title form ``del Comú de`` is read only from
    the instrument title.
    """

    folded = _latin_fold(normalize_legal_text(text)).casefold()
    if not folded:
        return False
    if _ANDORRAN_PARISH.search(folded) is not None:
        return True
    return title and _ANDORRAN_PARISH_TITLE.search(folded) is not None


def _municipal_instrument(row: Mapping[str, object]) -> bool:
    """True when the citation or the statute names a municipal issuer.

    A ``zakon``, ``uredba``, or ``zakonik`` that mentions municipalities stays.
    An ``odlok`` of ``Skupščina občine Kočevje`` or ``proračuna Občine
    Ravne-Prevalje`` does not. A Latvian ``saistošie noteikumi``, municipal
    fee, or municipal charter does not. A Cabinet regulation that only
    mentions municipalities stays. An Andorran ``Comú`` or ``Consell de
    Comú`` does not. A Consell General law that only mentions the Comuns
    stays. Slovenian issuer phrases are read from the statute text. The
    Latvian check reads the instrument title. The Andorran check reads
    the instrument title and the statute text.
    """

    identity = _latin_fold(_identity_text(row)).casefold()
    token = _instrument_token(identity) if identity else ""
    if token in _NATIONAL_INSTRUMENT_TOKENS:
        return False
    if identity and _MUNICIPAL_ISSUER.search(identity) is not None:
        return True
    if _latvian_municipal_title(_string(row.get("instrument_title"))):
        return True
    if _andorran_parish_text(_string(row.get("instrument_title")), title=True):
        return True
    statute = _statute_text(row)
    if not statute:
        return False
    folded = _latin_fold(statute).casefold()
    if _MUNICIPAL_TEXT.search(folded) is not None:
        return True
    return _andorran_parish_text(statute)


def municipal_issuer_law_ids(rows: Iterable[Mapping[str, object]]) -> set[str]:
    """Law ids that contain a municipal issuer on any article.

    A later article that only says the instrument takes effect is the same
    municipal instrument and is refused with it.
    """

    found: set[str] = set()
    for row in rows:
        law_id = _string(row.get("law_id"))
        if law_id and _municipal_instrument(row):
            found.add(law_id)
    return found


def _jurisdiction_code(row: Mapping[str, object]) -> str | None:
    resolved = _resolved_jurisdiction(row)
    if resolved is None or resolved.admin_level not in _NATIONAL_LEVELS:
        return None
    return resolved.code


def _fill_admin_level(jurisdiction: object) -> str:
    resolved = resolve_jurisdiction(jurisdiction if isinstance(jurisdiction, str) else "")
    if resolved is not None and resolved.admin_level == "supranational":
        return "supranational"
    return "country"


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


def _drop_gazette_number(atom: dict[str, object]) -> dict[str, object]:
    """Do not file the Sbírka item number as the section of the whole instrument."""

    text = atom.get("text")
    provenance = atom.get("provenance")
    if not isinstance(text, str) or not isinstance(provenance, dict):
        return atom
    match = _CZECH_COLLECTION.match(text)
    if match is None:
        return atom
    number = match.group(1)
    if re.search(rf"(?m)^§\s*{re.escape(number)}\b", text):
        return atom
    removed = False
    for key in ("section", "article"):
        if provenance.get(key) == number:
            provenance.pop(key, None)
            removed = True
    path = provenance.get("hierarchy_path")
    if isinstance(path, str) and re.fullmatch(
        rf"(?i)(?:section|article)\s+{re.escape(number)}", path.strip()
    ):
        provenance["hierarchy_path"] = ""
        removed = True
    if not removed or _located(provenance):
        return atom
    instrument = provenance.get("heading_instrument")
    if not isinstance(instrument, str) or not instrument.strip():
        title = atom.get("title")
        instrument = title if isinstance(title, str) else ""
        if instrument:
            provenance["heading_instrument"] = instrument
    language = atom.get("language")
    provenance["heading_status"] = "instrument_only"
    provenance["heading_evidence"] = "instrument"
    provenance["heading_placement"] = classify_placement(
        text,
        language if isinstance(language, str) else "",
        status="instrument_only",
        instrument=instrument if isinstance(instrument, str) else "",
    )
    return atom


def _with_japanese_whole_instrument(atom: dict[str, object]) -> dict[str, object]:
    """File a heading-less Japanese statute under its law name.

    The era law number and a leading paragraph ``1`` are not articles.
    """

    text = atom.get("text")
    provenance = atom.get("provenance")
    if not isinstance(text, str) or not isinstance(provenance, dict):
        return atom
    if not _ja_whole_instrument(text):
        return atom
    for key in ("section", "article", "chapter", "part", "title"):
        provenance.pop(key, None)
    path = provenance.get("hierarchy_path")
    if isinstance(path, str) and path.strip():
        provenance["hierarchy_path"] = ""
    statute = provenance.get("statute")
    if isinstance(statute, str) and re.fullmatch(r"[0-9]{1,4}", statute.strip()):
        provenance.pop("statute", None)
    instrument = provenance.get("heading_instrument")
    if not isinstance(instrument, str) or not instrument.strip():
        title = atom.get("title")
        instrument = title.strip() if isinstance(title, str) else ""
        if instrument:
            provenance["heading_instrument"] = instrument
    if not isinstance(instrument, str) or not instrument.strip():
        return atom
    provenance["heading_status"] = "instrument_only"
    provenance["heading_evidence"] = "instrument"
    language = atom.get("language")
    provenance["heading_placement"] = classify_placement(
        text,
        language if isinstance(language, str) else "ja",
        status="instrument_only",
        instrument=instrument,
    )
    return atom


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
    if assignment.status in {"instrument_only", "unresolved"}:
        body = atom.get("text")
        language = atom.get("language")
        provenance["heading_placement"] = classify_placement(
            body if isinstance(body, str) else "",
            language if isinstance(language, str) else "",
            status=assignment.status,
            instrument=assignment.instrument,
        )
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


def _zh_letters(line: str) -> int:
    return len(re.findall(r"[^\W\d_]", line))


def _zh_article_prose(text: str) -> bool:
    """True when a ``第 N 條`` line has a sentence, or a list of short items, and is not only a deletion."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    saw_label = False
    for line in lines:
        match = _ZH_ARTICLE_LINE.match(line)
        if match is None:
            continue
        saw_label = True
        rest = match.group("rest").strip()
        if (
            rest
            and _ZH_DELETE.match(rest) is None
            and "請參閱" not in rest
            and "请参阅" not in rest
            and _zh_letters(rest) >= 8
        ):
            return True
    if not saw_label:
        return False
    total = 0
    for line in lines:
        if _ZH_ARTICLE_LINE.match(line) or _ZH_DELETE.match(line):
            continue
        if "請參閱" in line or "请参阅" in line or "圖表附檔" in line or "图表附档" in line:
            continue
        total += _zh_letters(line)
    return total >= 8


def _en_article_prose(text: str) -> bool:
    """True when an English ``Article N`` line has a sentence and is not omitted."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    saw_label = False
    total = 0
    for line in lines:
        match = _EN_ARTICLE_LINE.match(line)
        if match is not None:
            saw_label = True
            rest = match.group("rest").strip()
            if rest and _EN_OMIT.match(rest) is None and _ZH_DELETE.match(rest) is None:
                total += _zh_letters(rest)
            continue
        if _EN_OMIT.match(line) or _ZH_DELETE.match(line):
            continue
        total += _zh_letters(line)
    return saw_label and total >= 8


def _nl_body(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and _NL_LABEL.match(lines[0]):
        lines = lines[1:]
    return " ".join(lines).strip()


def _nl_shell(text: str) -> bool:
    """A Dutch article whose only text is a repeal, a reservation, or a pointer."""

    body = _nl_body(text)
    if not body:
        return False
    if _NL_REPEAL.match(body):
        return True
    return _NL_POINTER.match(body) is not None and len(body) <= 180


def _nl_article_prose(text: str) -> bool:
    """True when a short Dutch ``Artikel N`` line is an operative sentence."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or _NL_LABEL.match(lines[0]) is None or _nl_shell(text):
        return False
    body = _nl_body(text)
    words = re.findall(r"[^\W\d_]{2,}", body)
    if len(words) < 4 or not re.search(r"[.!?]", body):
        return False
    first = lines[1].lstrip("([")
    return bool(first) and first[0].isupper()


def _pl_body_lines(text: str) -> list[str] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or _PL_LABEL.match(lines[0]) is None:
        return None
    body = lines[1:]
    while body and body[-1] in _PL_QUOTE_END:
        body = body[:-1]
    return body or None


def _pl_article_prose(text: str) -> bool:
    """True when a short Polish ``§ N`` or ``Art. N`` line is an operative sentence."""

    body = _pl_body_lines(text)
    if not body:
        return False
    blob = " ".join(body)
    if _PL_SHELL.search(blob) or _PL_DIRT.search(text) or _PL_PAGEJUMP.search(text):
        return False
    if any(_PL_SECOND.match(line) or _PL_CHAPTER.match(line) or _PL_FOOTNOTE.match(line) for line in body):
        return False
    for line in body:
        if re.fullmatch(r"[0-9]+\)", line):
            continue
        digits = sum(character.isdigit() for character in line)
        letters = sum(character.isalpha() for character in line)
        if digits > 3 and digits >= letters:
            return False
        if re.search(r"[A-Za-z]\s'[A-Za-z]|[A-Za-z]'[A-Za-z]", line):
            return False
    words = re.findall(r"[^\W\d_]{2,}", blob)
    if len(words) < 4 or not re.search(r"[.!?]", blob):
        return False
    if not re.search(r"[.!?)]\s*$", body[-1]):
        return False
    for index, line in enumerate(body):
        if not _PL_MARKER.match(line):
            continue
        if index + 1 == len(body) or _PL_MARKER.match(body[index + 1]):
            return False
    first = body[0].lstrip("([\"„”")
    if not first or not first[0].isupper():
        return False
    # ``art. 20 § 3`` inside the sentence is a citation. A second number would
    # file that citation as its own provision and cut the sentence.
    numbers = {
        unit.number.casefold()
        for unit in segment_exclusive(text, language="pl")
        if unit.kind in {"article", "section"} and unit.number
    }
    return len(numbers) == 1


def _id_article_prose(text: str) -> bool:
    """True when a short Indonesian ``Pasal N`` line is one closed provision."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    # A lowercase ``pasal`` line is a citation, and the stamp leaves it
    # without an article number. The label has to be ``Pasal``.
    label = _ID_LABEL.match(lines[0])
    if label is None or not lines[0].startswith("Pasal "):
        return False
    if label.group(1).casefold().endswith("l"):
        return False
    body = lines[1:]
    if (
        _ID_SHELL.search(text)
        or _ID_ELLIPSIS.search(text)
        or _ID_CAMEL.search(text)
        or _ID_MARK.search(text)
    ):
        return False
    if any(_ID_HEADER.match(line) or _ID_NEXT.match(line) or _ID_LIHAT.match(line) for line in body):
        return False
    if len(body) != len(set(body)):
        return False
    words = re.findall(r"[^\W\d_]{2,}", " ".join(body))
    if len(words) < 4 or not re.search(r"[.!?]$", body[-1]):
        return False
    units = segment_exclusive(text, language="id")
    if len(units) != 1 or units[0].kind != "article":
        return False
    if units[0].number != label.group(1) or units[0].body != text:
        return False
    return True


def _ko_article_prose(text: str) -> bool:
    """True when a Korean row is only one effective-date article."""

    match = korean_commencement_line(text)
    if match is None:
        return False
    expected = match.group(1) if match.group(2) is None else f"{match.group(1)}의{match.group(2)}"
    units = segment_exclusive(text, language="ko")
    if len(units) != 1 or units[0].kind != "article":
        return False
    return units[0].number == expected and units[0].body == text


_HR_LABEL = re.compile(r"(?i)^članak\s+([0-9]+[a-z]?)\.\s*$")
_HR_SIGN = re.compile(r"(?i)klasa:|urbroj:|v\.\s*r\.")
_HR_NEXT = re.compile(r"(?i)^članak\s+[0-9]")


_SV_LABEL = re.compile(r"^([0-9]{1,4})(\s*)([a-z])?\s*§(?![:a-z])\s*(.*)$")
_SV_SHELL = re.compile(
    r"(?i)^(?:har\s+)?(?:up+phävts|utgått|upphört att gälla|upphör att gälla)\b"
    r"|^ny beteckning\b"
)


def _sv_expected_number(match: re.Match[str]) -> str:
    digits = match.group(1)
    letter = match.group(3)
    if not letter:
        return digits
    if match.group(2):
        return f"{digits} {letter}"
    return f"{digits}{letter}"


def _sv_section_prose(text: str) -> bool:
    """True when a Swedish ``N §`` line is one closed section."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    label = _SV_LABEL.match(lines[0])
    if label is None or section_repeal_note(text):
        return False
    if any(_SV_LABEL.match(line) for line in lines[1:]):
        return False
    body_lines = [label.group(4).strip()] if label.group(4).strip() else []
    body_lines.extend(lines[1:])
    if not body_lines or not body_lines[0][:1].isupper():
        return False
    if _SV_SHELL.match(body_lines[0]):
        return False
    words = re.findall(r"[^\W\d_]{2,}", " ".join(body_lines))
    if len(words) < 3 or not re.search(r"[.!?]$", lines[-1]):
        return False
    units = segment_exclusive(text, language="sv")
    if len(units) != 1 or units[0].kind != "section":
        return False
    return units[0].number == _sv_expected_number(label) and units[0].body == text


def _hr_article_prose(text: str) -> bool:
    """True when a Croatian ``Članak N.`` line is one closed provision."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    label = _HR_LABEL.match(lines[0])
    if label is None or _HR_SIGN.search(text):
        return False
    if any(_HR_NEXT.match(line) for line in lines[1:]):
        return False
    body = lines[1:]
    words = re.findall(r"[^\W\d_]{2,}", " ".join(body))
    if len(words) < 4 or not re.search(r"[.!?]$", body[-1]):
        return False
    units = segment_exclusive(text, language="hr")
    if len(units) != 1 or units[0].kind != "article":
        return False
    return units[0].number == label.group(1) and units[0].body == text


# A Meiji-to-Reiwa statute with no article heading is the whole instrument.
# ``元年`` is year one. The law number on that line is not an article.
_JA_NUM = r"[0-9一二三四五六七八九十百千]+"
_JA_YEAR = r"(?:元|[0-9一二三四五六七八九十百千]+)"
_JA_ERA_LINE = re.compile(
    rf"^(?:明治|大正|昭和|平成|令和){_JA_YEAR}年法律第{_JA_NUM}号$"
)
_JA_ARTICLE_LINE = re.compile(rf"^第{_JA_NUM}条")
_JA_STUB_LINE = re.compile(r"^(?:削除|廃止)$")
_JA_OMITTED = re.compile(r"^(?:[0-9一二三四五六七八九十]+[ \t]*)?略$")
_JA_FOREIGN = re.compile(rf"第{_JA_NUM}条の規定は、")
_JA_FUKO_ARTICLE = re.compile(rf"^附\s*則\s+第{_JA_NUM}")
_JA_END = re.compile(r"(?:[。．!?？]|ものとする|[スズリムジ]|得)$")
_JA_PERIOD = re.compile(r"[。．]")
_JA_PARA = re.compile(r"^(?:附\s*則\s*)?([0-9]{1,3})(?:\s|$)")


def _ja_paragraph_gap(lines: list[str]) -> bool:
    previous: int | None = None
    for line in lines:
        if line.startswith("附"):
            previous = None
        match = _JA_PARA.match(line)
        if match is None:
            continue
        number = int(match.group(1))
        if previous is not None and number > previous + 1:
            return True
        previous = number
    return False


_AM_ETH = re.compile(r"[\u1200-\u137C]")
_AM_LAT = re.compile(r"[A-Za-z]")
_AM_ELLIPSIS = re.compile(r"\.{3,}|…")
_AM_HEAD = re.compile(r"(?m)^[ \t]*([0-9]{1,3})\.\s+\S")
_AM_PARTICLE = frozenset("የበከለወና")


def _am_broken_spacing(lines: list[str]) -> bool:
    """True when OCR has split Amharic words into single letters."""

    singles = 0
    for line in lines:
        for token in line.split():
            core = token.strip("፣፤።፡:;,።.\"“”«»()[]")
            letters = _AM_ETH.findall(core)
            if len(letters) == 1 and len(core) == 1 and letters[0] not in _AM_PARTICLE:
                singles += 1
                if singles >= 3:
                    return True
    return False


def _am_closed_section(text: str) -> str:
    """Section number of one closed Amharic ``N.`` provision, or empty.

    The number is the only line-start ``N.`` heading. ``1)`` stays an
    item. The row has to end on ``።`` or ``::``.
    """

    if _AM_ELLIPSIS.search(text):
        return ""
    if len(_AM_ETH.findall(text)) < 40 or len(_AM_LAT.findall(text)) >= 40:
        return ""
    if not text.strip().endswith(("።", "::")):
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return ""
    headings = _AM_HEAD.findall(text)
    if len(headings) != 1 or _AM_HEAD.match(lines[0]) is None:
        return ""
    if _am_broken_spacing(lines[1:]):
        return ""
    return headings[0]


def _am_whole_section(
    record: Mapping[str, object],
    cleaned: str,
    number: str,
) -> dict[str, object]:
    """One atom whose text is the cleaned provision and whose section is ``N.``."""

    atom = dict(record)
    atom["text"] = cleaned
    atom["content_sha256"] = sha256_text(cleaned)
    role, reason = classify_document_role(
        {
            "title": atom.get("title"),
            "language": atom.get("language"),
            "source_url": atom.get("source_url"),
            "text": cleaned,
        }
    )
    atom["provenance"] = {
        "atomic": True,
        "document_role": role,
        "document_role_reason": reason,
        "section": number,
        "statute": number,
        "hierarchy_path": f"Section {number}",
    }
    return atom


_SK_HEAD = re.compile(r"(?i)^čl\.\s+([IVXLCDM]+|\d+[a-z]?)$")
_SK_EFFECT = re.compile(
    r"(?i)^(?:tento|táto|toto)\s+\S+\s+nadobúda\s+(?:účinnosť|platnosť|záväznosť)\b.+\.$"
)
_SK_SIGN = re.compile(r"(?i)\bv\.\s*r\.\s*$")
_SK_BAD = re.compile(r"(?i)[ÃÅ]|â€|Â|\.{3,}|…|portál|slov-lex|prevziať")


def _sk_commencement(text: str) -> str:
    """Article token of one Slovak commencement clause, or empty.

    The row is ``Čl. N``, one sentence that the act takes effect, and
    optional ``v. r.`` signature lines. A second sentence, a citation,
    a form title, and broken encoding stay out.
    """

    if _SK_BAD.search(text):
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return ""
    match = _SK_HEAD.fullmatch(lines[0])
    if match is None:
        return ""
    body = [line for line in lines[1:] if _SK_SIGN.search(line) is None]
    if len(body) != 1:
        return ""
    sentence = body[0]
    if _SK_EFFECT.fullmatch(sentence) is None:
        return ""
    # A period is not a word character, so a boundary after "čl." never fires.
    # The same is true around "§". An internal citation or a second sentence
    # stays out; the date form "1. januára" has no capital after the period.
    if re.search(r"(?i)čl\.|§", sentence):
        return ""
    if re.search(r"\.\s+[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ]", sentence):
        return ""
    if len(re.findall(r"[^\W\d_]", sentence)) < 25:
        return ""
    return match.group(1)


def _sk_whole_article(
    record: Mapping[str, object],
    cleaned: str,
    number: str,
) -> dict[str, object]:
    """One atom whose text is the cleaned clause and whose article is ``Čl. N``."""

    atom = dict(record)
    atom["text"] = cleaned
    atom["content_sha256"] = sha256_text(cleaned)
    role, reason = classify_document_role(
        {
            "title": atom.get("title"),
            "language": atom.get("language"),
            "source_url": atom.get("source_url"),
            "text": cleaned,
        }
    )
    atom["provenance"] = {
        "atomic": True,
        "document_role": role,
        "document_role_reason": reason,
        "article": number,
        "hierarchy_path": f"Article {number}",
    }
    return atom


def _ja_whole_instrument(text: str) -> bool:
    """True when a Japanese law-number line is one whole statute."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not any(_JA_ERA_LINE.match(line) for line in lines):
        return False
    if any(_JA_ARTICLE_LINE.match(line) or _JA_STUB_LINE.match(line) for line in lines):
        return False
    if any(_JA_OMITTED.match(line) or _JA_FUKO_ARTICLE.match(line) for line in lines):
        return False
    if _JA_FOREIGN.search(text) or _ja_paragraph_gap(lines):
        return False
    if _JA_END.search(lines[-1]) is None:
        return False
    for line in lines:
        if _JA_ERA_LINE.match(line) or line.startswith("附"):
            continue
        # A schedule may follow the period on the same line. A classical
        # sentence may end in ジ, as in 亦同ジ.
        if _JA_END.search(line) or _JA_PERIOD.search(line):
            return True
    return False


def _provision_prose(text: str) -> bool:
    """True when the cleaned row is a provision, not a caption or a label table."""

    if _caption_shell(text):
        return False
    if _STATUTORY.search(text):
        return True
    if (
        _zh_article_prose(text)
        or _en_article_prose(text)
        or _nl_article_prose(text)
        or _pl_article_prose(text)
        or _id_article_prose(text)
        or _ko_article_prose(text)
        or _hr_article_prose(text)
        or _sv_section_prose(text)
        or _ja_whole_instrument(text)
    ):
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


def _with_code_title(atom: dict[str, object]) -> dict[str, object]:
    """Copy a code-provision title onto the one unsplit atom."""

    provenance = atom.get("provenance")
    text = atom.get("text")
    if not isinstance(provenance, dict) or not isinstance(text, str):
        return atom
    if _located(provenance):
        return atom
    code = locators_from_code_title(atom.get("title"), text)
    if not code:
        return atom
    number = code.get("article") or code.get("section") or ""
    if not number:
        return atom
    if "article" in code:
        provenance["article"] = code["article"]
        provenance.setdefault("section", code.get("section") or code["article"])
        provenance.setdefault("hierarchy_path", f"Article {code['article']}")
    else:
        provenance["section"] = code["section"]
        provenance.setdefault("hierarchy_path", f"Section {code['section']}")
    statute = provenance.get("statute")
    if not isinstance(statute, str) or not statute.strip():
        provenance["statute"] = number
    return atom


_SOLE_ANNEX = frozenset({"annexe", "annex", "anexo", "anlage", "appendix"})
# A provision line is ``Article únic``, ``Articolo unico.``, or ``Art. 1``
# and nothing else on that line. ``article 3r,`` and ``"Article 12`` are
# citations exposed by a line break. A sentence that continues on the same
# line is not this label.
_SOLE_LABEL = re.compile(r"^(?:Article|Articolo|Art\.)\s+\S+\.?\s*$")
# Normattiva wraps a repealed shell as ``((PROVVEDIMENTO ABROGATO ...))``.
# The operative text of that shell is the notice. A statute that only
# mentions an earlier repeal is longer than this and stays.
_REPEAL_SHELL = re.compile(
    r"(?i)^(?:\(\(|\[)?\s*(?:provvedimento|articolo|comma|decreto)\s+"
    r"(?:abrogat|soppress|decadut)\b"
)


def _citation_article_heading(heading: str) -> bool:
    """True for a wrapped citation rather than a provision line.

    ``article 3r,`` and ``l'article 10`` cite another instrument. ``"Article
    12`` quotes one. ``Article 1`` followed by its own sentence stays.
    """

    stripped = heading.strip()
    if not stripped:
        return True
    first = stripped[0]
    if first.islower() or first in {'"', "«", "(", "'", "’"}:
        return True
    folded = stripped.casefold()
    return folded.startswith("l'") or folded.startswith("l’")


def _repeal_shell(body: object) -> bool:
    """True when the article text is only an editorial repeal notice."""

    if not isinstance(body, str):
        return False
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if lines and _SOLE_LABEL.match(lines[0]):
        lines = lines[1:]
    blob = " ".join(lines).strip()
    if not blob or len(blob) > 220:
        return False
    folded = blob.casefold()
    if "provvedimento abrogato" in folded:
        return True
    return _REPEAL_SHELL.match(blob) is not None


def _sole_provision_unit(text: str, unit: object) -> bool:
    """True when the only heading is its own article line.

    ``Article únic`` or ``Art. 1`` on its own line is a provision. A
    citation such as ``l'article 10 de la Constitució``, ``article 3r,``,
    or a quoted ``"Article 12`` is not. A single letter, such as ``Can. C``,
    is not. An Italian repeal banner is not.
    """

    start = getattr(unit, "char_start", None)
    number = getattr(unit, "number", "")
    heading = getattr(unit, "heading", "")
    kind = getattr(unit, "kind", "")
    if not isinstance(start, int) or not isinstance(number, str) or not isinstance(heading, str):
        return False
    if kind != "article":
        return False
    if start > 0 and (start >= len(text) or text[start - 1] != "\n"):
        return False
    if len(number) == 1 and number.isalpha():
        return False
    if _SOLE_LABEL.match(heading.strip()) is None:
        return False
    return not _repeal_shell(getattr(unit, "body", ""))


def _with_sole_heading(atom: dict[str, object], language: str) -> dict[str, object]:
    """Copy the only article or section heading onto an unsplit instrument.

    A Catalan statute often opens with the preamble and then ``Article únic``.
    An Italian statute often opens with the promulgation formula and then
    ``Art. 1`` or ``Articolo unico.``. One heading does not divide the row.
    The whole text stays, and that heading is the locator. An annex label
    is not a provision number. A repeal banner is not.
    """

    provenance = atom.get("provenance")
    text = atom.get("text")
    if not isinstance(provenance, dict) or not isinstance(text, str):
        return atom
    if _located(provenance):
        return atom
    units = segment_exclusive(text, language=language if isinstance(language, str) else "")
    found = [
        unit
        for unit in units
        if unit.kind in {"article", "section"}
        and unit.number
        and unit.number.casefold() not in _SOLE_ANNEX
        and len(unit.body.strip()) >= 16
        and _sole_provision_unit(text, unit)
    ]
    if len(found) != 1:
        return atom
    unit = found[0]
    number = unit.number.strip()
    if unit.kind == "article":
        provenance["article"] = number
        provenance.setdefault("section", number)
        provenance.setdefault("hierarchy_path", f"Article {number}")
    else:
        provenance["section"] = number
        provenance.setdefault("hierarchy_path", f"Section {number}")
    statute = provenance.get("statute")
    if not isinstance(statute, str) or not statute.strip():
        provenance["statute"] = number
    return atom


def _with_leading_heading(atom: dict[str, object], language: str) -> dict[str, object]:
    """Copy one leading article or section number onto the unsplit atom."""

    provenance = atom.get("provenance")
    text = atom.get("text")
    if not isinstance(provenance, dict) or not isinstance(text, str):
        return atom
    if _located(provenance):
        return atom
    punkts = locators_from_punkts_title(atom.get("title"), text)
    if punkts:
        number = punkts["article"]
        provenance["article"] = number
        provenance.setdefault("section", number)
        provenance.setdefault("hierarchy_path", f"Article {number}")
        statute = provenance.get("statute")
        if not isinstance(statute, str) or not statute.strip():
            provenance["statute"] = number
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
        if unit.kind in _STRUCTURAL
        and unit.number
        and unit.number.casefold() not in _SOLE_ANNEX
        and len(unit.body.strip()) >= 16
        and (unit.kind != "article" or not _citation_article_heading(unit.heading))
    ]
    if not units:
        return atom
    provisions = [unit for unit in units if unit.kind in {"article", "section"}]
    if provisions:
        provision_numbers = {unit.number for unit in provisions}
        if len(provision_numbers) != 1:
            return atom
        others = [unit for unit in units if unit.kind not in {"article", "section"}]
        other_numbers = {unit.number for unit in others}
        if other_numbers and other_numbers != provision_numbers:
            lead = min(provisions, key=lambda unit: unit.char_start)
        else:
            lead = min(units, key=lambda unit: unit.char_start)
    else:
        numbers = {unit.number for unit in units}
        if len(numbers) != 1:
            return atom
        lead = min(units, key=lambda unit: unit.char_start)
    if lead.char_start > 80:
        return atom
    if section_repeal_note(text):
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
    if len(cleaned) >= _MIN_PROVISION and (
        _STATUTORY.search(cleaned) or _CZECH_ENACTING.search(cleaned)
    ):
        return True
    if _ja_whole_instrument(cleaned):
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
