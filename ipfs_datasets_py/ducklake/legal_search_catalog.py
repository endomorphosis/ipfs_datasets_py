"""Observational DuckDB catalog for country-IR legal search.

Stores release pins, shard locators, and BM25 term ranges. Document bodies
and embedding floats are not columns. Quack is not attached: production
catalog mutation stays behind the DuckLake promotion hold. The file must
not be the authoritative ``control.duckdb``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    CorpusRelease,
)
from ipfs_datasets_py.retrieval.hf_graphrag.engine import is_cidv1_key
from ipfs_datasets_py.retrieval.hf_graphrag.schema import MAX_ROWS_PER_PHYSICAL_SHARD

_COUNTRY_LAYOUT = "country-laws-ir-graphrag/v1"
_PUBLICUS_LAYOUT = "publicus-ir-graphrag/v2"
_PATENT_LAYOUT = "patent-legal-ir-graphrag"
_IR_LAYOUTS = frozenset({_COUNTRY_LAYOUT, _PUBLICUS_LAYOUT, _PATENT_LAYOUT})
_BM25_INDEX = Path("indexes") / "bm25_keyword_shards.parquet"
_BM25_KIND = "bm25_postings"
_RANGE_COLUMNS = ("first_key", "last_key", "sha256", "row_count", "shard_id")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_COLUMNS = frozenset({
    "text",
    "body",
    "html",
    "embedding",
    "vector",
    "token",
    "path",
})


class LegalSearchCatalogError(ValueError):
    """The legal search catalog refused a pin, path, or route."""

    def __init__(self, message: str, *, reason: str = "rejected") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Bm25Route:
    """One term routed to one posting shard. No document body."""

    corpus_id: str
    term: str
    shard_ordinal: int
    coverage: str
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False


@dataclass(frozen=True)
class LocalPinResult:
    """One local checkout considered for registration. No document body."""

    corpus_id: str
    hf_repo: str
    status: str
    ranges: int = 0

    def __post_init__(self) -> None:
        if self.status not in {
            "registered",
            "not_checked_out",
            "missing_index",
            "rejected",
            "skipped",
        }:
            raise LegalSearchCatalogError(f"unknown local pin status: {self.status}")
        if self.ranges < 0:
            raise LegalSearchCatalogError("range count cannot be negative")
        if self.status != "registered" and self.ranges != 0:
            raise LegalSearchCatalogError("only a registered pin has term ranges")


def assert_legal_search_path(path: str | Path) -> Path:
    """Refuse the authoritative control-plane database."""

    candidate = Path(path)
    lowered = str(candidate).lower().replace("\\", "/")
    if lowered.endswith("/control.duckdb") or candidate.name == "control.duckdb":
        raise LegalSearchCatalogError(
            "legal search catalog must not use control.duckdb"
        )
    if "/control.duckdb" in lowered:
        raise LegalSearchCatalogError(
            "legal search catalog must not use control.duckdb"
        )
    return candidate


def open_legal_search_catalog(path: str | Path):
    """Open a private legal-search DuckDB file and create compact tables."""

    catalog_path = assert_legal_search_path(path)
    if catalog_path.exists() and catalog_path.is_dir():
        raise LegalSearchCatalogError("legal search catalog path is a directory")
    import duckdb

    connection = duckdb.connect(str(catalog_path))
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_meta (
            catalog_name VARCHAR PRIMARY KEY,
            authoritative BOOLEAN NOT NULL,
            ducklake_authoritative BOOLEAN NOT NULL,
            quack_attached BOOLEAN NOT NULL,
            research_only BOOLEAN NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO catalog_meta
        VALUES ('legal_search', FALSE, FALSE, FALSE, TRUE)
        ON CONFLICT (catalog_name) DO NOTHING
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS corpus_release (
            corpus_id VARCHAR PRIMARY KEY,
            hf_repo VARCHAR NOT NULL,
            layout_profile VARCHAR NOT NULL,
            coverage VARCHAR NOT NULL,
            primary_key_field VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL,
            authoritative BOOLEAN NOT NULL,
            ducklake_authoritative BOOLEAN NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shard_locator (
            corpus_id VARCHAR NOT NULL,
            family VARCHAR NOT NULL,
            shard_ordinal INTEGER NOT NULL,
            content_sha256 VARCHAR NOT NULL,
            row_count INTEGER NOT NULL,
            PRIMARY KEY (corpus_id, family, shard_ordinal)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bm25_term_range (
            corpus_id VARCHAR NOT NULL,
            shard_ordinal INTEGER NOT NULL,
            term_low VARCHAR NOT NULL,
            term_high VARCHAR NOT NULL,
            PRIMARY KEY (corpus_id, shard_ordinal)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS document_index (
            corpus_id VARCHAR NOT NULL,
            entry_cid VARCHAR NOT NULL,
            shard_ordinal INTEGER NOT NULL,
            PRIMARY KEY (corpus_id, entry_cid)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_space (
            corpus_id VARCHAR NOT NULL,
            vector_space_id VARCHAR NOT NULL,
            model_id VARCHAR NOT NULL,
            dimensions INTEGER NOT NULL,
            fuse_with_bm25 BOOLEAN NOT NULL,
            PRIMARY KEY (corpus_id, vector_space_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_centroid (
            corpus_id VARCHAR NOT NULL,
            vector_space_id VARCHAR NOT NULL,
            centroid_id VARCHAR NOT NULL,
            shard_ordinal INTEGER NOT NULL,
            PRIMARY KEY (corpus_id, vector_space_id, centroid_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_alias (
            source_repo VARCHAR NOT NULL,
            alias_id VARCHAR NOT NULL,
            corpus_id VARCHAR NOT NULL,
            entry_cid VARCHAR NOT NULL,
            coverage VARCHAR NOT NULL,
            searchable BOOLEAN NOT NULL,
            PRIMARY KEY (source_repo, alias_id)
        )
        """
    )
    return connection


def _require_search_pin(release: CorpusRelease, layouts: frozenset[str]) -> None:
    if not isinstance(release, CorpusRelease):
        raise LegalSearchCatalogError("release must be a CorpusRelease")
    if release.layout_profile not in layouts or not release.selected:
        raise LegalSearchCatalogError(
            f"{release.hf_repo} is not a selected search pin"
        )
    if release.authoritative or release.ducklake_authoritative or not release.research_only:
        raise LegalSearchCatalogError("search pin must stay observational")


def _range_row(raw: Mapping[str, object]) -> tuple[str, int, str, str, str, int]:
    corpus_id = str(raw.get("corpus_id") or "").strip()
    term_low = str(raw.get("term_low") or "").strip()
    term_high = str(raw.get("term_high") or "").strip()
    digest = str(raw.get("content_sha256") or "").strip().lower()
    try:
        ordinal = int(raw.get("shard_ordinal"))  # type: ignore[arg-type]
        row_count = int(raw.get("row_count"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise LegalSearchCatalogError("shard ordinal and row count must be integers") from exc
    if not corpus_id or not term_low or not term_high or term_low > term_high:
        raise LegalSearchCatalogError("BM25 term range is empty or inverted")
    if ordinal < 0 or row_count < 1 or row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise LegalSearchCatalogError("BM25 shard is outside the physical row bound")
    if _SHA256.fullmatch(digest) is None:
        raise LegalSearchCatalogError("shard content hash must be sha256 hex")
    return corpus_id, ordinal, term_low, term_high, digest, row_count


def _reject_overlaps(ranges: Sequence[tuple[str, int, str, str, str, int]]) -> None:
    by_corpus: dict[str, list[tuple[str, str]]] = {}
    for corpus_id, _ordinal, term_low, term_high, _digest, _count in ranges:
        by_corpus.setdefault(corpus_id, []).append((term_low, term_high))
    for corpus_id, spans in by_corpus.items():
        ordered = sorted(spans)
        for (_low, high), (next_low, _next_high) in zip(ordered, ordered[1:]):
            if next_low <= high:
                raise LegalSearchCatalogError(
                    f"overlapping BM25 term ranges in {corpus_id}"
                )


def register_ir_catalog(
    connection,
    releases: Sequence[CorpusRelease],
    ranges: Sequence[Mapping[str, object]],
    documents: Sequence[Mapping[str, object]] = (),
    *,
    layouts: frozenset[str] = _IR_LAYOUTS,
) -> dict[str, int]:
    """Insert selected IR pins and compact routes.

    A document whose ``entry_cid`` is not CIDv1 is omitted. No body is read.
    """

    pins = tuple(releases)
    for release in pins:
        _require_search_pin(release, layouts)
    parsed = tuple(_range_row(item) for item in ranges)
    known = {release.corpus_id for release in pins}
    if any(item[0] not in known for item in parsed):
        raise LegalSearchCatalogError("term range names a corpus that is not selected")
    _reject_overlaps(parsed)
    for release in pins:
        connection.execute(
            """
            INSERT INTO corpus_release VALUES (?, ?, ?, ?, ?, TRUE, FALSE, FALSE)
            ON CONFLICT (corpus_id) DO NOTHING
            """,
            [
                release.corpus_id,
                release.hf_repo,
                release.layout_profile,
                release.coverage,
                release.primary_key,
            ],
        )
    for corpus_id, ordinal, term_low, term_high, digest, row_count in parsed:
        connection.execute(
            """
            INSERT INTO shard_locator VALUES (?, 'bm25_postings', ?, ?, ?)
            ON CONFLICT (corpus_id, family, shard_ordinal) DO NOTHING
            """,
            [corpus_id, ordinal, digest, row_count],
        )
        connection.execute(
            """
            INSERT INTO bm25_term_range VALUES (?, ?, ?, ?)
            ON CONFLICT (corpus_id, shard_ordinal) DO NOTHING
            """,
            [corpus_id, ordinal, term_low, term_high],
        )
    kept = 0
    omitted = 0
    for raw in documents:
        corpus_id = str(raw.get("corpus_id") or "").strip()
        entry_cid = str(raw.get("entry_cid") or "").strip()
        if corpus_id not in known or not is_cidv1_key(entry_cid):
            omitted += 1
            continue
        try:
            ordinal = int(raw.get("shard_ordinal"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            omitted += 1
            continue
        if ordinal < 0:
            omitted += 1
            continue
        connection.execute(
            """
            INSERT INTO document_index VALUES (?, ?, ?)
            ON CONFLICT (corpus_id, entry_cid) DO NOTHING
            """,
            [corpus_id, entry_cid, ordinal],
        )
        kept += 1
    return {"ranges": len(parsed), "documents_kept": kept, "documents_omitted": omitted}


def register_country_ir_catalog(
    connection,
    releases: Sequence[CorpusRelease],
    ranges: Sequence[Mapping[str, object]],
    documents: Sequence[Mapping[str, object]] = (),
) -> dict[str, int]:
    """Insert selected country pins and compact routes."""

    return register_ir_catalog(
        connection,
        releases,
        ranges,
        documents,
        layouts=frozenset({_COUNTRY_LAYOUT}),
    )


def _bm25_index_files(release_root: Path) -> tuple[Path, ...]:
    """Return compact BM25 index files. Document shard directories are ignored."""

    root = release_root.expanduser().resolve()
    target = root / _BM25_INDEX
    if target.is_file():
        candidates = (target,)
    elif target.is_dir():
        candidates = tuple(sorted(path for path in target.glob("*.parquet") if path.is_file()))
    else:
        raise LegalSearchCatalogError(
            "missing BM25 compact index indexes/bm25_keyword_shards.parquet",
            reason="missing_index",
        )
    if not candidates:
        raise LegalSearchCatalogError(
            "BM25 compact index directory has no parquet",
            reason="missing_index",
        )
    files: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise LegalSearchCatalogError(
                "BM25 compact index escaped the release root"
            ) from exc
        if not relative.parts or relative.parts[0] != "indexes":
            raise LegalSearchCatalogError("BM25 compact index must live under indexes/")
        if "data" in relative.parts:
            raise LegalSearchCatalogError("BM25 compact index must not read data shards")
        files.append(resolved)
    return tuple(files)


def load_bm25_term_ranges(
    release_root: str | Path,
    corpus_id: str,
) -> tuple[dict[str, object], ...]:
    """Read term ranges from the compact BM25 index only.

    ``relative_path`` and any text column in that file are not returned.
    Files under ``data/`` are not opened.
    """

    import pyarrow.parquet as pq

    source = str(corpus_id or "").strip()
    if not source:
        raise LegalSearchCatalogError("corpus_id is required")
    ranges: list[dict[str, object]] = []
    for path in _bm25_index_files(Path(release_root)):
        names = set(pq.read_schema(path).names)
        missing = [name for name in _RANGE_COLUMNS if name not in names]
        if missing:
            raise LegalSearchCatalogError(
                "BM25 compact index is missing routing columns: " + ", ".join(missing)
            )
        columns = list(_RANGE_COLUMNS)
        if "kind" in names:
            columns.append("kind")
        table = pq.read_table(path, columns=columns)
        kind_values = table.column("kind").to_pylist() if "kind" in columns else [""] * table.num_rows
        for first_key, last_key, digest, row_count, shard_id, kind in zip(
            table.column("first_key").to_pylist(),
            table.column("last_key").to_pylist(),
            table.column("sha256").to_pylist(),
            table.column("row_count").to_pylist(),
            table.column("shard_id").to_pylist(),
            kind_values,
        ):
            label = str(kind or "").strip()
            if label and label != _BM25_KIND:
                raise LegalSearchCatalogError(
                    f"BM25 compact index row has kind {label!r}"
                )
            ranges.append(
                {
                    "corpus_id": source,
                    "term_low": first_key,
                    "term_high": last_key,
                    "shard_ordinal": shard_id,
                    "content_sha256": str(digest or "").lower(),
                    "row_count": row_count,
                }
            )
    if not ranges:
        raise LegalSearchCatalogError("BM25 compact index has no term ranges")
    return tuple(ranges)


def register_country_ir_index(connection, release: CorpusRelease, release_root: str | Path) -> dict[str, int]:
    """Register one selected country pin from its compact BM25 index."""

    ranges = load_bm25_term_ranges(release_root, release.corpus_id)
    return register_country_ir_catalog(connection, (release,), ranges)


def register_ir_index(connection, release: CorpusRelease, release_root: str | Path) -> dict[str, int]:
    """Register one selected country, publicus, or patent pin from its compact index."""

    ranges = load_bm25_term_ranges(release_root, release.corpus_id)
    return register_ir_catalog(connection, (release,), ranges)


def _register_local_pins(
    connection,
    releases: Sequence[CorpusRelease],
    checkout_root: str | Path,
    layouts: frozenset[str],
) -> tuple[LocalPinResult, ...]:
    """Register selected pins in *layouts* from ``<checkout_root>/<repo name>``."""

    root = Path(checkout_root).expanduser().resolve()
    if not root.is_dir():
        raise LegalSearchCatalogError("checkout root must be a directory")
    results: list[LocalPinResult] = []
    chosen = sorted(
        (release for release in releases if release.layout_profile in layouts),
        key=lambda release: (release.corpus_id, release.hf_repo),
    )
    for release in chosen:
        if not release.selected:
            results.append(LocalPinResult(release.corpus_id, release.hf_repo, "skipped"))
            continue
        repo_name = release.hf_repo.split("/", 1)[-1]
        checkout = (root / repo_name).resolve()
        try:
            checkout.relative_to(root)
        except ValueError:
            results.append(LocalPinResult(release.corpus_id, release.hf_repo, "rejected"))
            continue
        if not checkout.is_dir():
            results.append(
                LocalPinResult(release.corpus_id, release.hf_repo, "not_checked_out")
            )
            continue
        try:
            counted = register_ir_index(connection, release, checkout)
        except LegalSearchCatalogError as exc:
            status = exc.reason if exc.reason == "missing_index" else "rejected"
            results.append(LocalPinResult(release.corpus_id, release.hf_repo, status))
            continue
        results.append(
            LocalPinResult(
                release.corpus_id,
                release.hf_repo,
                "registered",
                int(counted["ranges"]),
            )
        )
    for release in releases:
        if release.layout_profile in layouts:
            continue
        results.append(LocalPinResult(release.corpus_id, release.hf_repo, "skipped"))
    return tuple(results)


def register_local_country_ir_pins(
    connection,
    releases: Sequence[CorpusRelease],
    checkout_root: str | Path,
) -> tuple[LocalPinResult, ...]:
    """Register each selected country pin that has a local compact index.

    A checkout is ``<checkout_root>/<repo name>``. Missing checkouts and
    missing indexes are reported and skipped. Other country pins are not
    registered. Document shards are not opened.
    """

    return _register_local_pins(
        connection,
        releases,
        checkout_root,
        frozenset({_COUNTRY_LAYOUT}),
    )


def register_local_ir_pins(
    connection,
    releases: Sequence[CorpusRelease],
    checkout_root: str | Path,
) -> tuple[LocalPinResult, ...]:
    """Register selected country, publicus, and patent pins from local indexes.

    The Federal Register research snapshot and split patent repos stay
    unregistered. Document shards are not opened.
    """

    return _register_local_pins(connection, releases, checkout_root, _IR_LAYOUTS)


def route_bm25_terms(connection, terms: Iterable[str]) -> tuple[Bm25Route, ...]:
    """Route terms through stored ranges. Does not read document bodies."""

    routes: list[Bm25Route] = []
    seen: set[tuple[str, str, int]] = set()
    for term in terms:
        token = str(term or "").strip()
        if not token:
            continue
        rows = connection.execute(
            """
            SELECT range.corpus_id, range.shard_ordinal, release.coverage
            FROM bm25_term_range AS range
            JOIN corpus_release AS release
              ON release.corpus_id = range.corpus_id
            WHERE range.term_low <= ? AND range.term_high >= ?
            ORDER BY range.corpus_id, range.shard_ordinal
            """,
            [token, token],
        ).fetchall()
        per_corpus: dict[str, int] = {}
        for corpus_id, ordinal, _coverage in rows:
            per_corpus[str(corpus_id)] = per_corpus.get(str(corpus_id), 0) + 1
        if any(count > 1 for count in per_corpus.values()):
            raise LegalSearchCatalogError(f"overlapping BM25 term ranges for {token!r}")
        for corpus_id, ordinal, coverage in rows:
            key = (str(corpus_id), token, int(ordinal))
            if key in seen:
                continue
            seen.add(key)
            routes.append(
                Bm25Route(
                    corpus_id=str(corpus_id),
                    term=token,
                    shard_ordinal=int(ordinal),
                    coverage=str(coverage),
                )
            )
    return tuple(routes)


def catalog_column_names(connection) -> frozenset[str]:
    """Column names materialised in the legal search catalog."""

    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
        """
    ).fetchall()
    return frozenset(str(row[0]).lower() for row in rows)


def assert_catalog_has_no_bodies(connection) -> None:
    """Fail if a body, embedding, path, or token column was added."""

    present = catalog_column_names(connection) & _FORBIDDEN_COLUMNS
    if present:
        raise LegalSearchCatalogError(
            f"legal search catalog stored forbidden columns: {sorted(present)}"
        )
