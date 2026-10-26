"""Copy one code name onto sibling rows of the same source law.

A whole-line code name is inherited only when that law contains exactly one
such name. A title that already names a loi or an ordonnance is left as it
is. Hierarchy numbers are copied only into empty locator fields, and only
from a heading that appears once in that law. Statute text is not rewritten.
Nothing is invented, downloaded, or uploaded, and the assembled corpus is
only read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.national_directory import (
    _HEADING_KIND,
    _HEADING_LINE,
    _ROMAN,
    _TITLE_LOI,
    _fold,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

INHERIT_VERSION = "instrument-inherit/v1"
_MAX_ATOMS = 250_000
_NORMALIZER = "country-source-admit/v1"
_HEADING_KEYS = ("book", "title", "chapter", "part", "section")
_CODE_LINE = re.compile(
    r"(?m)^CODE [A-ZÀÂÉÈÊËÎÏÔÙÛÜÇŒ][A-ZÀÂÉÈÊËÎÏÔÙÛÜÇŒ '&-]{4,}$"
)
_CODE_CAPTION = re.compile(r"(?i)^(code\b(?:[^\n>]{0,160}?))\s*>\s*article\b")
_CAPTION_TITLE = re.compile(
    r"(?i)^(?:"
    r"article|art\.?|section|sec\.?|livre|titre|titulo|título|chapitre|chapter|partie|part|title"
    r")"
    r"(?:[ \t]*[-–—.]?[ \t]*(?:"
    r"[0-9]{1,4}(?:[.\-][0-9]{1,4})?[A-Za-z]?|[IVXLCDM]{1,12}|1er"
    r"))?"
    r"[ \t]*(?:[.:\-–—]+)?[ \t]*$"
)


def inheritance_plan(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, tuple[str, dict[str, str]]]:
    """Map each law id to its single code name and its unique headings."""

    codes: dict[str, set[str]] = {}
    headings: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        law = row.get("law_id")
        if not isinstance(law, str) or not law.strip():
            continue
        text = _source_text(row)
        names = codes.setdefault(law, set())
        names.update(_CODE_LINE.findall(text))
        bucket = headings.setdefault(law, {})
        for line in [item.strip() for item in text.splitlines() if item.strip()][:80]:
            heading = _HEADING_LINE.match(line)
            if heading is None:
                continue
            kind = _HEADING_KIND[heading.group(1).casefold()]
            number = heading.group(2)
            number = number if number.isdigit() else number.upper()
            if not number.isdigit() and _ROMAN.fullmatch(number) is None:
                continue
            bucket.setdefault(kind, set()).add(number)
    plan: dict[str, tuple[str, dict[str, str]]] = {}
    for law, names in codes.items():
        if len(names) != 1:
            continue
        sole = {
            kind: next(iter(values))
            for kind, values in headings.get(law, {}).items()
            if len(values) == 1 and kind in _HEADING_KEYS
        }
        plan[law] = (next(iter(names)), sole)
    return plan


def replacement_title(title: str, text: str, law_code: str | None) -> str | None:
    """Return the code name to store as the record title, or None to keep it."""

    if not law_code:
        return None
    label = title.strip()
    if _names_other_instrument(label, text):
        return None
    if not label or _CAPTION_TITLE.fullmatch(label):
        return law_code
    caption = _CODE_CAPTION.match(label)
    if caption and _fold(caption.group(1)) == _fold(law_code):
        return law_code
    return None


def refine_atom(
    record: Mapping[str, object],
    *,
    law_code: str | None,
    headings: Mapping[str, str],
) -> dict[str, object]:
    """Fill a blank instrument title and empty hierarchy fields.

    The returned text is the input text. A loi or ordonnance title is not
    replaced by the parent code.
    """

    updated = dict(record)
    text = updated.get("text") if isinstance(updated.get("text"), str) else ""
    current = updated.get("title") if isinstance(updated.get("title"), str) else ""
    new_title = replacement_title(current, text, law_code)
    if new_title == current:
        new_title = None
    provenance, encoded = _copy_provenance(updated.get("provenance"))
    added: dict[str, str] = {}
    if provenance is not None and _accepts_hierarchy(current, text, law_code):
        for key in _HEADING_KEYS:
            value = headings.get(key, "")
            if not value:
                continue
            already = provenance.get(key)
            if isinstance(already, str) and already.strip():
                continue
            provenance[key] = value
            added[key] = value
        _note_jsonld(provenance, new_title, added)
    elif provenance is not None and new_title:
        _note_jsonld(provenance, new_title, {})
    if new_title:
        updated["title"] = new_title
    if provenance is not None and (new_title or added):
        updated["provenance"] = _store_provenance(provenance, encoded)
    if updated.get("text") != record.get("text"):
        raise ValueError("text")
    return updated


def refine_assembled_corpus(
    source_paths: Iterable[Path | str],
    assembled_dir: Path | str,
    dest_dir: Path | str,
    *,
    source_dataset: str,
    source_revision: str,
) -> dict[str, object]:
    """Write a sibling corpus whose titles carry a same-law code name.

    ``assembled_dir`` must already be a finished country fill. This function
    does not modify it, does not download, and does not upload.
    """

    assembled = Path(assembled_dir)
    destination = Path(dest_dir)
    _separate(assembled, destination)
    if not _is_sha(source_revision):
        raise ValueError("source_revision")
    report = _assembled_report(assembled)
    parts = sorted(assembled.glob("part-*.parquet"))
    if not parts:
        raise ValueError("assembled")
    total = _row_count(parts)
    if total < 1 or total > _MAX_ATOMS:
        raise ValueError("assembled")
    sources = [Path(path) for path in source_paths]
    if not sources or any(not path.is_file() for path in sources):
        raise ValueError("source")
    rows = _read_source_rows(sources)
    plan = inheritance_plan(rows)
    if not plan:
        return {
            "version": INHERIT_VERSION,
            "written": False,
            "titles_filled": 0,
            "headings_filled": 0,
            "reason": "no_sole_code",
            "normalizer_version": report.get("normalizer_version"),
        }
    law_by_cid = _law_by_entry_cid(
        rows,
        source_dataset=source_dataset,
        source_revision=source_revision,
    )
    destination.mkdir(parents=True, exist_ok=True)
    for stale in destination.glob("part-*.parquet"):
        stale.unlink()
    stale_report = destination / "refine_report.json"
    if stale_report.exists():
        stale_report.unlink()
    titles = 0
    heading_rows = 0
    unmatched = 0
    written: list[str] = []
    for index, part in enumerate(parts):
        refined: list[dict[str, object]] = []
        for record in _iter_part(part):
            cid = record.get("entry_cid") if isinstance(record.get("entry_cid"), str) else ""
            law = law_by_cid.get(cid, "")
            code, headings = plan.get(law, (None, {}))
            if not law:
                unmatched += 1
            before_title = record.get("title")
            before_provenance = record.get("provenance")
            atom = refine_atom(record, law_code=code, headings=headings if code else {})
            if atom.get("text") != record.get("text") or atom.get("entry_cid") != record.get("entry_cid"):
                raise ValueError("text")
            if atom.get("content_sha256") != record.get("content_sha256"):
                raise ValueError("text")
            if atom.get("title") != before_title:
                titles += 1
            if atom.get("provenance") != before_provenance and atom.get("title") == before_title:
                heading_rows += 1
            elif atom.get("provenance") != before_provenance and _gained_heading(before_provenance, atom.get("provenance")):
                heading_rows += 1
            refined.append(atom)
        written.append(_write_part(destination, index, refined))
    summary = {
        "version": INHERIT_VERSION,
        "written": True,
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "atoms": total,
        "titles_filled": titles,
        "headings_filled": heading_rows,
        "unmatched": unmatched,
        "laws": len(plan),
        "files": [Path(path).name for path in written],
        "normalizer_version": report.get("normalizer_version"),
    }
    stale_report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _names_other_instrument(title: str, text: str) -> bool:
    if _TITLE_LOI.match(title):
        return True
    for line in text.splitlines():
        if line.strip():
            return _TITLE_LOI.match(line.strip()) is not None
    return False


def _accepts_hierarchy(title: str, text: str, law_code: str | None) -> bool:
    if not law_code:
        return False
    if _fold(title) == _fold(law_code):
        return True
    return replacement_title(title, text, law_code) is not None


def _source_text(row: Mapping[str, object]) -> str:
    body = row.get("body")
    if isinstance(body, str) and body:
        return body
    text = row.get("text")
    return text if isinstance(text, str) else ""


def _copy_provenance(value: object) -> tuple[dict[str, object] | None, bool]:
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return None, True
        if isinstance(loaded, dict):
            return loaded, True
        return None, True
    if isinstance(value, dict):
        loaded = json.loads(json.dumps(value))
        if isinstance(loaded, dict):
            return loaded, False
    return None, False


def _store_provenance(provenance: Mapping[str, object], encoded: bool) -> str | dict[str, object]:
    if encoded:
        return json.dumps(provenance, sort_keys=True, ensure_ascii=False)
    copied = json.loads(json.dumps(provenance))
    return copied if isinstance(copied, dict) else {}


def _note_jsonld(provenance: dict[str, object], name: str | None, added: Mapping[str, str]) -> None:
    document = provenance.get("jsonld")
    if not isinstance(document, dict):
        return
    before = document.get("text")
    if name:
        document["name"] = name
    if added:
        properties = document.get("additionalProperty")
        if not isinstance(properties, list):
            properties = []
            document["additionalProperty"] = properties
        present = {
            item.get("propertyID")
            for item in properties
            if isinstance(item, dict) and isinstance(item.get("propertyID"), str)
        }
        for key, value in added.items():
            if key in present:
                continue
            properties.append({"@type": "PropertyValue", "propertyID": key, "value": value})
    if document.get("text") != before:
        raise ValueError("text")


def _gained_heading(before: object, after: object) -> bool:
    old, _old_encoded = _copy_provenance(before)
    new, _new_encoded = _copy_provenance(after)
    if old is None or new is None:
        return False
    for key in _HEADING_KEYS:
        previous = old.get(key)
        current = new.get(key)
        if (not isinstance(previous, str) or not previous.strip()) and isinstance(current, str) and current.strip():
            return True
    return False


def _separate(assembled: Path, destination: Path) -> None:
    source = assembled.resolve()
    target = destination.resolve()
    if source == target or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("dest")


def _assembled_report(assembled: Path) -> dict[str, object]:
    path = assembled / "report.json"
    if not path.is_file():
        raise ValueError("assembled")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("assembled") from exc
    if not isinstance(loaded, dict):
        raise ValueError("assembled")
    if loaded.get("corpus_complete") is not True:
        raise ValueError("assembled")
    if loaded.get("normalizer_version") != _NORMALIZER:
        raise ValueError("assembled")
    return loaded


def _row_count(parts: list[Path]) -> int:
    import pyarrow.parquet as pq

    return sum(pq.ParquetFile(path).metadata.num_rows for path in parts)


def _read_source_rows(paths: list[Path]) -> list[dict[str, object]]:
    import pyarrow.parquet as pq

    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import _FILL_COLUMNS

    rows: list[dict[str, object]] = []
    wanted = ("law_id", *_FILL_COLUMNS)
    for path in paths:
        present = [name for name in wanted if name in pq.read_schema(path).names]
        if "law_id" not in present:
            continue
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=256, columns=present):
            rows.extend(batch.to_pylist())
    return rows


def _law_by_entry_cid(
    rows: Iterable[Mapping[str, object]],
    *,
    source_dataset: str,
    source_revision: str,
) -> dict[str, str]:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import (
        _fill_row,
        _is_sha,
        admit_source_law,
    )

    found: dict[str, str] = {}
    blocked: set[str] = set()
    for row in rows:
        law = row.get("law_id")
        if not isinstance(law, str) or not law.strip():
            continue
        revision = row.get("source_revision")
        pin = revision if _is_sha(revision) else source_revision
        decision = admit_source_law(
            _fill_row(row),
            source_dataset=source_dataset,
            source_revision=pin,
        )
        if not decision.admitted:
            continue
        for atom in decision.records:
            cid = atom.get("entry_cid")
            if not isinstance(cid, str) or not cid:
                continue
            previous = found.get(cid)
            if previous is None:
                found[cid] = law
            elif previous != law:
                blocked.add(cid)
    for cid in blocked:
        found.pop(cid, None)
    return found


def _iter_part(path: Path) -> Iterable[dict[str, object]]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    present = [name for name in LEGAL_RECORD_FIELDS if name in pq.read_schema(path).names]
    for batch in parquet.iter_batches(batch_size=256, columns=present):
        yield from batch.to_pylist()


def _write_part(destination: Path, index: int, records: list[dict[str, object]]) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([pa.field(name, pa.string()) for name in LEGAL_RECORD_FIELDS])
    columns = {
        name: [
            record.get(name) if isinstance(record.get(name), str) else None
            for record in records
        ]
        for name in LEGAL_RECORD_FIELDS
    }
    part = destination / f"part-{index:06d}.parquet"
    pq.write_table(pa.table(columns, schema=schema), part, compression="zstd")
    return str(part)


def _is_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value)
    )
