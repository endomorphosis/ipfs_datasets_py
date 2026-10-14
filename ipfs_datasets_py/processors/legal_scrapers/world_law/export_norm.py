"""Write a local legal-record/v1 tree. This module does not upload.

Hub cutover stays off. ``--upload`` raises ``ExportUploadBlocked`` and does
not construct a Hugging Face client. The module does not read ``HF_TOKEN``,
``HF_TOKEN_FILE``, or the Hugging Face token cache.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.world_law.project_american_municipal_row import (
    project_american_municipal_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_html_municipal_row import (
    project_html_municipal_row,
)
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


class ExportRefused(ValueError):
    """The local tree cannot be written for this slug or revision."""


class ExportUploadBlocked(RuntimeError):
    """Hub upload is not part of this command."""


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
    ``coverage=not_published``.
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
    records = _project(source, family, source_dataset, source_revision, gap_status, counts)
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
    if dry_run:
        return summary
    dest = Path(dest_dir)
    if dest.exists() and any(dest.iterdir()):
        raise ExportRefused(f"destination is not empty: {dest}")
    files = _write_parts(records, dest, rows_per_file) if kept else []
    manifest = {
        "schema_version": "legal-record/v1",
        "family": family,
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "destination_repo": repo,
        "normalizer_version": _normalizer_version(family),
        "rows_kept": kept,
        "rows_dropped": summary["rows_dropped"],
        "filter_counts": summary["filter_counts"],
        "coverage": summary["coverage"],
        "license_note": "research-only",
        "commit_shas": [],
        "previous_revision": None,
        "provenance_encoding": "json",
    }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (dest / "README.md").write_text(_readme(manifest), encoding="utf-8")
    summary["files"] = [str(path.relative_to(dest)) for path in files] + [
        "manifest.json",
        "README.md",
    ]
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


def _project(
    source: Path,
    family: str,
    source_dataset: str,
    source_revision: str,
    gap_status: str | None,
    counts: Counter[str],
) -> list[dict[str, object]]:
    html = family == "html"
    rows = list(_parquet_rows(source, html=html))
    if not rows:
        raise ExportRefused(f"no {('html' if html else 'text')} parquet rows in {source}")
    kept: list[dict[str, object]] = []
    for row in rows:
        record = _one(row, family, source_dataset, source_revision, gap_status, counts)
        if record is None:
            continue
        counts["kept"] += 1
        kept.append(_encode(record))
    return kept


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
    )
    if record is None:
        counts["dropped"] += 1
        return None
    provenance = record["provenance"]
    if isinstance(provenance, dict):
        provenance["query_default"] = gap_status in {"stale", "missing", "incomplete"}
    return record


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


def _parquet_rows(source: Path, *, html: bool) -> Iterator[dict[str, object]]:
    if not source.is_dir():
        raise ExportRefused(f"source directory does not exist: {source}")
    files = [
        path
        for path in sorted(source.rglob("*.parquet"))
        if ("_html" in path.name) is html and ".cache" not in path.parts
    ]
    for path in files:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=5000):
            yield from batch.to_pylist()


def _normalizer_version(family: str) -> str:
    if family == "html":
        return "html-municipal-scraper/v1+legal-record/v1"
    if family == "american":
        return "american-municipal-html/v1+legal-record/v1"
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
