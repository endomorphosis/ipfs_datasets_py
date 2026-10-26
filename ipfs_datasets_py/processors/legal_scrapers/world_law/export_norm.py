"""Write a local legal-record/v1 tree. This module does not upload.

Hub cutover stays off. ``--upload`` raises ``ExportUploadBlocked`` and does
not construct a Hugging Face client. The module does not read ``HF_TOKEN``,
``HF_TOKEN_FILE``, or the Hugging Face token cache.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.world_law.project_american_municipal_row import (
    NORMALIZER_VERSION as AMERICAN_NORMALIZER_VERSION,
    heading_after,
    origin_urls_from_html,
    project_american_municipal_row,
    resolve_place,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_html_municipal_row import (
    project_html_municipal_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
    render_atomic,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import strip_markup
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    drop_reason,
    project_world_v11_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

_SHA_LEN = 40
_ROWS_PER_FILE = 20_000
_BLOCKED_DESTINATIONS = frozenset({
    "justicedao/american_municipal_law",
    "justicedao/ipfs_state_laws",
    "justicedao/ipfs_federal_register",
})
HTML_MUNICIPAL_SLUGS = frozenset({
    "belgium_municipal",
    "canada_municipal",
    "indonesia_municipal",
    "portugal_municipal",
    "new_zealand_municipal",
})
_FAMILIES = frozenset({"html", "american", "world-national", "world-municipal"})
_RECORD_SCHEMA = pa.schema([pa.field(name, pa.string()) for name in LEGAL_RECORD_FIELDS])
# world_municipal_law README at 5adaca491711041b297664294fda9bfecea0c62e names
# these configs. They are absent from that card's provenance table. A dry-run
# count of zero is not_published. This writer does not invent their rows.
_CARD_CONFIGS_WITHOUT_PROVENANCE = ("CL", "HU")


class ExportRefused(ValueError):
    """The local tree cannot be written for this slug or revision."""


class ExportUploadBlocked(RuntimeError):
    """Hub upload is not part of this command."""


def is_world_v11_shard(name: str) -> bool:
    """Return whether this basename is a 34-column world-law row file.

    Published world corpora store statutes in ``*_html.parquet``.
    ``places.parquet`` and ``articles*.parquet`` are not law rows.
    """

    base = _basename(name)
    if base == "places.parquet" or base.startswith("articles"):
        return False
    return base.endswith("_html.parquet")


def choose_export_command(slug: str, siblings: Sequence[str]) -> str:
    """Return the one command that may read this sibling list.

    Exact ``data/laws.parquet`` is ``reindex``. Other ``laws-*.parquet``
    files are ``load_sharded_laws``. HTML-only shards are
    ``export_norm_html``. An empty list is ``not_published``.
    """

    bases = [_basename(name) for name in siblings]
    exact = "laws.parquet" in bases
    shards = any(_is_law_shard(name) for name in bases)
    html = any(name.endswith(".parquet") and "_html" in name for name in bases)
    if slug in HTML_MUNICIPAL_SLUGS:
        if exact or shards:
            raise ExportRefused(
                f"{slug} is an HTML-only municipal slug and cannot use reindex or load_sharded_laws"
            )
        return "export_norm_html" if html else "not_published"
    if exact:
        return "reindex"
    if shards:
        return "load_sharded_laws"
    if html:
        return "export_norm_html"
    return "not_published"


def destination_repo(family: str, slug: str | None = None) -> str:
    if family == "html":
        if not slug:
            raise ExportRefused("an HTML municipal export needs a slug")
        repo = f"justicedao/ipfs_{slug}_laws_norm"
    elif family == "american":
        repo = "justicedao/american_municipal_law_norm"
    elif family == "world-national":
        repo = "justicedao/world_national_law"
    elif family == "world-municipal":
        repo = "justicedao/world_municipal_law"
    else:
        raise ExportRefused(f"unknown export family: {family}")
    if repo in _BLOCKED_DESTINATIONS:
        raise ExportRefused(f"{repo} is not an export destination")
    return repo


def export_norm(
    source_dir: Path,
    dest_dir: Path,
    *,
    family: str,
    source_dataset: str,
    source_revision: str,
    slug: str | None = None,
    gap_status: str | None = None,
    dry_run: bool = False,
    rows_per_file: int = _ROWS_PER_FILE,
) -> dict[str, object]:
    """Project a local parquet directory into a legal-record/v1 tree.

    ``dry_run`` counts rows and writes nothing. Zero kept rows report
    ``coverage=not_published``. Each kept row is one atomic legal unit.
    Chrome-only text is counted as ``not_atomic`` and is not written. A null
    ``text`` cell is kept with ``provenance.atomic`` false.
    """

    if family not in _FAMILIES:
        raise ExportRefused(f"unknown export family: {family}")
    if not isinstance(source_revision, str) or len(source_revision) != _SHA_LEN:
        raise ExportRefused("source_revision must be 40 lowercase hex characters")
    if any(char not in "0123456789abcdef" for char in source_revision):
        raise ExportRefused("source_revision must be 40 lowercase hex characters")
    if os.environ.get("HF_TOKEN_FILE"):
        raise ExportRefused("HF_TOKEN_FILE is not used by export_norm")
    repo = destination_repo(family, slug)
    source = Path(source_dir)
    if family == "html":
        _refuse_text_shards(source)
    counts: Counter[str] = Counter()
    card_kept: Counter[str] = Counter()
    encoded = _iter_encoded(
        source,
        family,
        source_dataset,
        source_revision,
        gap_status,
        counts,
        card_kept,
    )
    dest = Path(dest_dir)
    files: list[Path] = []
    staging: Path | None = None
    if dry_run:
        for _record in encoded:
            pass
    else:
        if dest.exists() and any(dest.iterdir()):
            raise ExportRefused(f"destination is not empty: {dest}")
        staging = dest.parent / f".{dest.name}.export-partial"
        if staging.exists():
            raise ExportRefused(f"partial export exists: {staging}")
        staging.mkdir(parents=True)
        try:
            files = _write_parts(encoded, staging, rows_per_file)
            if not counts["kept"]:
                for child in staging.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                files = []
            kept = counts["kept"]
            summary = _summary(
                family, source_dataset, source_revision, repo, counts, dry_run, card_kept
            )
            manifest = _manifest(summary)
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            (staging / "README.md").write_text(_readme(manifest), encoding="utf-8")
            relative = [str(path.relative_to(staging)) for path in files]
            if dest.exists():
                dest.rmdir()
            staging.rename(dest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        summary["files"] = relative + ["manifest.json", "README.md"]
        return summary
    summary = _summary(
        family, source_dataset, source_revision, repo, counts, dry_run, card_kept
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_norm")
    parser.add_argument("--family", required=True, choices=sorted(_FAMILIES))
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--slug", default=None)
    parser.add_argument("--gap-status", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    if args.upload:
        raise ExportUploadBlocked(
            "Hub upload is blocked until the canary matrix passes. export_norm writes a local tree only."
        )
    summary = export_norm(
        Path(args.source),
        Path(args.out),
        family=args.family,
        source_dataset=args.source_dataset,
        source_revision=args.revision,
        slug=args.slug,
        gap_status=args.gap_status,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))
    return 0


def _summary(
    family: str,
    source_dataset: str,
    source_revision: str,
    repo: str,
    counts: Counter[str],
    dry_run: bool,
    card_kept: Counter[str],
) -> dict[str, object]:
    kept = counts["kept"]
    summary: dict[str, object] = {
        "family": family,
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "destination_repo": repo,
        "rows_kept": kept,
        "rows_dropped": sum(value for key, value in counts.items() if key != "kept"),
        "filter_counts": {key: value for key, value in sorted(counts.items()) if key != "kept"},
        "coverage": "snapshot" if kept else "not_published",
        "dry_run": dry_run,
        "files": [],
    }
    if family == "world-municipal":
        summary["card_config_counts"] = _card_config_counts(card_kept)
    return summary


def _manifest(summary: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": "legal-record/v1",
        "family": summary["family"],
        "source_dataset": summary["source_dataset"],
        "source_revision": summary["source_revision"],
        "destination_repo": summary["destination_repo"],
        "normalizer_version": _normalizer_version(str(summary["family"])),
        "rows_kept": summary["rows_kept"],
        "rows_dropped": summary["rows_dropped"],
        "filter_counts": summary["filter_counts"],
        "coverage": summary["coverage"],
        "license_note": "research-only",
        "commit_shas": [],
        "previous_revision": None,
        "provenance_encoding": "json",
    }


def _iter_encoded(
    source: Path,
    family: str,
    source_dataset: str,
    source_revision: str,
    gap_status: str | None,
    counts: Counter[str],
    card_kept: Counter[str],
) -> Iterator[dict[str, object]]:
    saw_row = False
    for row in _parquet_rows(source, family=family):
        saw_row = True
        record = _one(row, family, source_dataset, source_revision, gap_status, counts)
        if record is None:
            continue
        atoms = expand_legal_record(record)
        if not atoms:
            counts["not_atomic"] += 1
            continue
        for atom in atoms:
            if family == "american":
                # The body splitter records adopted-code headings. The chunk
                # title and the heading stack are the municipal position.
                _keep_american_structure(record, atom)
                _attach_jsonld(atom)
            counts["kept"] += 1
            encoded = _encode(atom)
            code = str(encoded.get("jurisdiction") or "").upper()
            if code in _CARD_CONFIGS_WITHOUT_PROVENANCE:
                card_kept[code] += 1
            yield encoded
    if not saw_row:
        raise ExportRefused(f"no {_row_kind(family)} parquet rows in {source}")


def _one(
    row: Mapping[str, object],
    family: str,
    source_dataset: str,
    source_revision: str,
    gap_status: str | None,
    counts: Counter[str],
) -> dict[str, object] | None:
    if family == "html":
        record = project_html_municipal_row(
            row,
            source_repo=source_dataset,
            source_revision=source_revision,
        )
        if record is None:
            counts["unknown_country"] += 1
        return record
    if family == "american":
        return project_american_municipal_row(
            row,
            source_repo=source_dataset,
            source_revision=source_revision,
            place_name=_text_or_none(row.get("_place_name")),
            state_code=_text_or_none(row.get("_state_code")),
            chapter_num=_text_or_none(row.get("_chapter_num")),
            heading_stack=_heading_stack(row.get("_heading_stack")),
        )
    reason = drop_reason(row, drop_us=True)
    if reason is not None:
        counts[reason] += 1
        return None
    record = project_world_v11_row(
        row,
        source_repo=source_dataset,
        source_revision=source_revision,
        drop_us=True,
        admin_level="municipality" if family == "world-municipal" else "country",
    )
    if record is None:
        counts["dropped"] += 1
        return None
    provenance = record["provenance"]
    if isinstance(provenance, dict):
        provenance["query_default"] = gap_status in {"stale", "missing", "incomplete"}
    return record


def _card_config_counts(card_kept: Counter[str]) -> dict[str, dict[str, object]]:
    counts: dict[str, dict[str, object]] = {}
    for code in _CARD_CONFIGS_WITHOUT_PROVENANCE:
        rows = int(card_kept[code])
        counts[code] = {
            "rows_kept": rows,
            "coverage": "snapshot" if rows else "not_published",
            "provenance_table": False,
        }
    return counts


def _encode(record: Mapping[str, object]) -> dict[str, object]:
    encoded: dict[str, object] = {}
    for field in LEGAL_RECORD_FIELDS:
        value = record.get(field)
        if field == "provenance":
            encoded[field] = json.dumps(value if isinstance(value, dict) else {}, sort_keys=True)
        elif value is None:
            encoded[field] = None
        else:
            encoded[field] = str(value)
    if "html" in encoded:
        raise ExportRefused("legal-record/v1 export must not contain html")
    return encoded


def _write_parts(records: Sequence[Mapping[str, object]], dest: Path, rows_per_file: int) -> list[Path]:
    if rows_per_file < 1:
        raise ExportRefused("rows_per_file must be at least 1")
    written: list[Path] = []
    buffer: list[Mapping[str, object]] = []

    def flush() -> None:
        if not buffer:
            return
        index = len(written)
        path = dest / "data" / f"part-{index:04d}" / "laws.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(list(buffer), schema=_RECORD_SCHEMA)
        pq.write_table(table, path)
        written.append(path)
        buffer.clear()

    for record in records:
        buffer.append(record)
        if len(buffer) >= rows_per_file:
            flush()
    flush()
    if len(written) == 1:
        target = dest / "data" / "laws.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        written[0].replace(target)
        part_dir = dest / "data" / "part-0000"
        if part_dir.is_dir():
            part_dir.rmdir()
        return [target]
    return written


def _row_kind(family: str) -> str:
    if family in {"world-national", "world-municipal"}:
        return "world-law shard"
    if family == "html":
        return "html"
    return "text"


def _keep_parquet(path: Path, family: str) -> bool:
    if ".cache" in path.parts:
        return False
    if family in {"world-national", "world-municipal"}:
        return is_world_v11_shard(path.name)
    if family == "american":
        # The ordinance frame is the 5-column ``*_html.parquet``.
        # ``*_citation.parquet`` is a sidecar and is not a legal-record row.
        return path.name.endswith("_html.parquet")
    return ("_html" in path.name) is (family == "html")


# World projection never reads ``html``. Skipping that column avoids decoding
# the largest field in each shard. Other families still read every column.
_WORLD_READ_COLUMNS = (
    "cid",
    "country_code",
    "source_policy",
    "source_official",
    "content_complete",
    "text",
    "doc_type",
    "title_native",
    "html_title",
    "number",
    "official_citation",
    "language",
    "published_date",
    "effective_date",
    "source_org",
    "source_platform",
    "source_url",
    "original_url",
    "archive_source",
    "archive_crawl_id",
    "archive_timestamp",
    "archive_url",
    "license_note",
    "possibly_stale",
    "in_force",
    "consolidated",
)


def _read_columns(names: list[str], family: str) -> list[str] | None:
    if family not in {"world-national", "world-municipal"}:
        return None
    present = set(names)
    chosen = [name for name in _WORLD_READ_COLUMNS if name in present]
    return chosen or None


def _parquet_rows(source: Path, *, family: str) -> Iterator[dict[str, object]]:
    if not source.is_dir():
        raise ExportRefused(f"source directory does not exist: {source}")
    files = [path for path in sorted(source.rglob("*.parquet")) if _keep_parquet(path, family)]
    progress = os.environ.get("EXPORT_NORM_PROGRESS") == "1"
    total = len(files)
    if family == "american":
        places = _american_places(source)
        yield from _american_html_rows(files, places, progress=progress, total=total)
        return
    for index, path in enumerate(files, start=1):
        if progress:
            print(f"PROGRESS {index}/{total} {path.name}", file=sys.stderr, flush=True)
        parquet = pq.ParquetFile(path)
        columns = _read_columns(list(parquet.schema_arrow.names), family)
        batches = (
            parquet.iter_batches(batch_size=5000, columns=columns)
            if columns is not None
            else parquet.iter_batches(batch_size=5000)
        )
        for batch in batches:
            yield from batch.to_pylist()


def _american_places(source: Path) -> dict[str, tuple[str, str]]:
    """Stem to ``(place_name, state_code)``. The scrape clock is not loaded."""

    found: dict[str, tuple[str, str]] = {}
    for path in source.rglob("*.json"):
        if ".cache" in path.parts or path.parent.name != "metadata":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        place = data.get("place_name")
        state = data.get("state_code")
        found[path.stem] = (
            place.strip() if isinstance(place, str) else "",
            state.strip() if isinstance(state, str) else "",
        )
    return found


def _american_html_rows(
    files: Sequence[Path],
    places: Mapping[str, tuple[str, str]],
    *,
    progress: bool,
    total: int,
) -> Iterator[dict[str, object]]:
    for index, path in enumerate(files, start=1):
        if progress:
            print(f"PROGRESS {index}/{total} {path.name}", file=sys.stderr, flush=True)
        place, state = places.get(_html_stem(path), ("", ""))
        rows: list[dict[str, object]] = []
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=5000):
            rows.extend(batch.to_pylist())
        rows.sort(key=_doc_order)
        titles = [
            title
            for title in (strip_markup(row.get("html_title")) for row in rows)
            if title
        ]
        place_name, state_code = resolve_place(
            place, state, titles, gnis=_html_stem(path)
        )
        if place_name is None and state_code is None:
            urls: list[str] = []
            seen_urls: set[str] = set()
            for row in rows:
                for url in origin_urls_from_html(row.get("html")):
                    if url not in seen_urls:
                        seen_urls.add(url)
                        urls.append(url)
            if urls:
                place_name, state_code = resolve_place(place, state, titles, urls)
        stack: tuple[tuple[str, str], ...] = ()
        for row in rows:
            title = strip_markup(row.get("html_title"))
            stack = heading_after(title, stack)
            enriched = dict(row)
            enriched["_place_name"] = place_name
            enriched["_state_code"] = state_code
            enriched["_heading_stack"] = stack
            yield enriched


def _html_stem(path: Path) -> str:
    suffix = "_html.parquet"
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]
    return path.stem


def _doc_order(row: Mapping[str, object]) -> tuple[int, str]:
    raw = row.get("doc_order")
    try:
        order = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        order = 0
    if order < 0:
        order = 0
    return order, str(row.get("doc_id") or "")


def _text_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _heading_stack(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        return ()
    stack: list[tuple[str, str]] = []
    for item in value:
        if (
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
            and item[0]
            and item[1]
        ):
            stack.append((item[0], item[1]))
    return tuple(stack)


_AMERICAN_STRUCTURE = (
    "title",
    "chapter",
    "article",
    "division",
    "part",
    "section",
    "hierarchy_path",
)
# The body splitter must not invent a parent heading. A table of contents
# that mentions "Chapter 1105" is not that chapter.
_STACK_KEYS = ("title", "chapter", "article", "division", "part")


def _keep_american_structure(
    parent: Mapping[str, object], atom: dict[str, object]
) -> None:
    """Put the chunk's headings back after the body splitter.

    A municipal section title such as ``101.03`` stays the section. A
    ``Section 6103`` or ``Chapter 1105`` line inside the ordinance is not a
    new heading. When the chunk itself has no section number, a section found
    in the body stays and is appended to the parent headings.
    """

    parent_prov = parent.get("provenance")
    atom_prov = atom.get("provenance")
    if not isinstance(parent_prov, dict) or not isinstance(atom_prov, dict):
        return
    parent_has_structure = any(
        isinstance(parent_prov.get(key), str) and parent_prov.get(key)
        for key in (*_STACK_KEYS, "section", "hierarchy_path")
    )
    for key in _AMERICAN_STRUCTURE:
        value = parent_prov.get(key)
        if isinstance(value, str) and value:
            atom_prov[key] = value
        elif parent_has_structure and key in _STACK_KEYS:
            atom_prov.pop(key, None)
    parent_section = parent_prov.get("section")
    parent_path = parent_prov.get("hierarchy_path")
    atom_section = atom_prov.get("section")
    if (
        not (isinstance(parent_section, str) and parent_section)
        and isinstance(parent_path, str)
        and parent_path
        and isinstance(atom_section, str)
        and atom_section
    ):
        suffix = "Section " + atom_section
        if not parent_path.endswith(suffix):
            atom_prov["hierarchy_path"] = parent_path + " / " + suffix


def _attach_jsonld(record: dict[str, object]) -> None:
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return
    provenance["jsonld"] = render_atomic(record, "jsonld")


def _normalizer_version(family: str) -> str:
    if family == "html":
        return "html-municipal-scraper/v1+legal-record/v1"
    if family == "american":
        return AMERICAN_NORMALIZER_VERSION
    return "world-law/v1.1.0+legal-record/v1"


def _readme(manifest: Mapping[str, object]) -> str:
    return (
        "---\n"
        "license: other\n"
        "---\n\n"
        f"# {manifest['destination_repo']}\n\n"
        "Research-only projection into `legal-record/v1`. "
        "This tree is not an official source of law. "
        "A query for a jurisdiction that is not published returns an empty typed result.\n\n"
        f"Source dataset: `{manifest['source_dataset']}`\n\n"
        f"Source revision: `{manifest['source_revision']}`\n\n"
        f"Rows kept: {manifest['rows_kept']}\n"
    )


def _basename(name: str) -> str:
    return str(name).rstrip("/").split("/")[-1]


def _is_law_shard(name: str) -> bool:
    return name.startswith("laws-") and name.endswith(".parquet") and "_html" not in name


def _refuse_text_shards(source: Path) -> None:
    if not source.is_dir():
        return
    for path in source.rglob("*.parquet"):
        name = path.name
        if name == "laws.parquet" or _is_law_shard(name):
            raise ExportRefused(
                "html export refuses a directory that also contains text law shards"
            )


if __name__ == "__main__":
    raise SystemExit(main())
