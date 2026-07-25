"""Scalable full-corpus BM25 index keyed by canonical SkillCenter CIDs.

SQLite FTS5 provides the persisted bag-of-words postings and Okapi BM25
ranking. The virtual table is contentless: source bodies are tokenized into
the index but cannot be read back from it. A compact metadata table uses
``entry_cid`` as its primary key and maps the same key to the FTS rowid.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Any, Final

from ipfs_datasets_py.processors.retrieval import tokenize_lexical_text

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from ...profile_g import validate_cid
from .skillcenter_corpus import (
    SKILLCENTER_CORPUS_PRIMARY_KEY,
    SkillCenterCorpusIndex,
)


SKILLCENTER_CORPUS_BM25_SCHEMA_VERSION: Final = (
    "skillcenter-corpus-bm25/v1"
)
SKILLCENTER_CORPUS_BM25_DOCUMENT_SCHEMA_VERSION: Final = (
    "skillcenter-corpus-bm25-document/v1"
)
SKILLCENTER_CORPUS_BM25_TOKENIZER: Final = (
    "sqlite-fts5-unicode61-remove-diacritics-2/v1"
)
DEFAULT_TITLE_WEIGHT: Final = 2.0
DEFAULT_BODY_WEIGHT: Final = 1.0
DEFAULT_MAX_QUERY_TERMS: Final = 64
DEFAULT_BUILD_BATCH_SIZE: Final = 256

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class SkillCenterCorpusBM25Error(ValueError):
    """Raised when a full-corpus BM25 artifact is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterCorpusBM25Config:
    """Stable FTS5 indexing and query configuration."""

    title_weight: float = DEFAULT_TITLE_WEIGHT
    body_weight: float = DEFAULT_BODY_WEIGHT
    max_query_terms: int = DEFAULT_MAX_QUERY_TERMS
    tokenizer: str = SKILLCENTER_CORPUS_BM25_TOKENIZER

    def __post_init__(self) -> None:
        for name in ("title_weight", "body_weight"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise SkillCenterCorpusBM25Error(
                    f"{name} must be finite and positive"
                )
            object.__setattr__(self, name, value)
        if (
            isinstance(self.max_query_terms, bool)
            or not isinstance(self.max_query_terms, int)
            or not 1 <= self.max_query_terms <= 1024
        ):
            raise SkillCenterCorpusBM25Error(
                "max_query_terms must be between 1 and 1024"
            )
        if self.tokenizer != SKILLCENTER_CORPUS_BM25_TOKENIZER:
            raise SkillCenterCorpusBM25Error("unsupported BM25 tokenizer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_weight": self.body_weight,
            "max_query_terms": self.max_query_terms,
            "title_weight": self.title_weight,
            "tokenizer": self.tokenizer,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillCenterCorpusBM25BuildSummary:
    output_dir: str
    dataset_revision: str
    indexed_entries: int
    primary_key: str
    sqlite_cid: str
    sqlite_size_bytes: int
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_revision": self.dataset_revision,
            "indexed_entries": self.indexed_entries,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "primary_key": self.primary_key,
            "sqlite_cid": self.sqlite_cid,
            "sqlite_size_bytes": self.sqlite_size_bytes,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterCorpusBM25Hit:
    entry_cid: str
    document_index: int
    score: float
    matched_terms: tuple[str, ...]
    metadata: Mapping[str, Any]
    authority: str = "context_only"
    proof_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.entry_cid
            or self.document_index < 0
            or not math.isfinite(float(self.score))
            or self.score < 0
            or self.authority != "context_only"
            or self.proof_authority is not False
        ):
            raise SkillCenterCorpusBM25Error("BM25 hit is malformed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "matched_terms": list(self.matched_terms),
            "metadata": dict(self.metadata),
            "proof_authority": self.proof_authority,
            "score": self.score,
        }


class SkillCenterCorpusBM25Index:
    """Verified read-only search facade over the CID-keyed FTS5 index."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        database_path: Path,
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.database_path = database_path
        self.config = SkillCenterCorpusBM25Config(
            **dict(manifest["config"])
        )

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        corpus_dir: str | Path | None = None,
        verify_integrity: bool = True,
    ) -> "SkillCenterCorpusBM25Index":
        index_root = Path(root).expanduser().resolve()
        manifest_path = index_root / "manifest.json"
        if (
            index_root.is_symlink()
            or not index_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterCorpusBM25Error(
                "BM25 index must contain a bounded regular manifest"
            )
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterCorpusBM25Error(
                "BM25 manifest is malformed"
            ) from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema_version")
            != SKILLCENTER_CORPUS_BM25_SCHEMA_VERSION
            or manifest.get("primary_key")
            != SKILLCENTER_CORPUS_PRIMARY_KEY
        ):
            raise SkillCenterCorpusBM25Error("unsupported BM25 manifest")
        database_path = _verify_file_descriptor(
            index_root,
            manifest.get("sqlite"),
        )
        config = SkillCenterCorpusBM25Config(**dict(manifest["config"]))
        if manifest.get("config_sha256") != config.digest:
            raise SkillCenterCorpusBM25Error("BM25 config digest mismatch")
        uri = f"{database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view')"
                )
            }
            if not {
                "documents",
                "documents_fts",
                "documents_vocab",
            } <= tables:
                raise SkillCenterCorpusBM25Error(
                    "BM25 SQLite schema is incomplete"
                )
            expected = int(manifest.get("indexed_entries", -1))
            document_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            )
            fts_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM documents_fts"
                ).fetchone()[0]
            )
            unique_cids = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT entry_cid) FROM documents"
                ).fetchone()[0]
            )
            if {document_count, fts_count, unique_cids} != {expected}:
                raise SkillCenterCorpusBM25Error(
                    "BM25 document/CID coverage is inconsistent"
                )
            sample = connection.execute(
                "SELECT title, body FROM documents_fts LIMIT 1"
            ).fetchone()
            if sample is not None and sample != (None, None):
                raise SkillCenterCorpusBM25Error(
                    "BM25 FTS table must be contentless"
                )
            if verify_integrity:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if result is None or result[0] != "ok":
                    raise SkillCenterCorpusBM25Error(
                        "BM25 SQLite integrity check failed"
                    )
        loaded = cls(
            root=index_root,
            manifest=manifest,
            database_path=database_path,
        )
        if corpus_dir is not None:
            loaded.verify_corpus_coverage(corpus_dir)
        return loaded

    @property
    def summary(self) -> SkillCenterCorpusBM25BuildSummary:
        descriptor = self.manifest["sqlite"]
        return SkillCenterCorpusBM25BuildSummary(
            output_dir=str(self.root),
            dataset_revision=str(self.manifest["dataset_revision"]),
            indexed_entries=int(self.manifest["indexed_entries"]),
            primary_key=str(self.manifest["primary_key"]),
            sqlite_cid=str(descriptor["cid"]),
            sqlite_size_bytes=int(descriptor["size_bytes"]),
            manifest_sha256=hashlib.sha256(
                (self.root / "manifest.json").read_bytes()
            ).hexdigest(),
        )

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        exclude_entry_cid: str = "",
        filters: Mapping[str, str] | None = None,
    ) -> tuple[SkillCenterCorpusBM25Hit, ...]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 1000:
            raise SkillCenterCorpusBM25Error("k must be between 1 and 1000")
        terms = _query_terms(query, self.config)
        if not terms:
            return ()
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return self._search_connection(
                connection,
                terms=terms,
                k=k,
                exclude_entry_cid=exclude_entry_cid,
                filters=filters,
            )

    def _search_connection(
        self,
        connection: sqlite3.Connection,
        *,
        terms: Sequence[str],
        k: int,
        exclude_entry_cid: str = "",
        filters: Mapping[str, str] | None = None,
        explain: bool = True,
        title_only: bool = False,
    ) -> tuple[SkillCenterCorpusBM25Hit, ...]:
        if not terms:
            return ()
        expression = " OR ".join(
            (
                "title : " + _quote_fts_term(term)
                if title_only
                else _quote_fts_term(term)
            )
            for term in terms
        )
        clauses = ["documents_fts MATCH ?"]
        parameters: list[Any] = [expression]
        if exclude_entry_cid:
            validate_cid(exclude_entry_cid, path="/exclude_entry_cid")
            clauses.append("d.entry_cid != ?")
            parameters.append(exclude_entry_cid)
        allowed_filters = {
            "domain",
            "language",
            "profile",
            "repository_file",
            "source_type",
        }
        for key, value in sorted((filters or {}).items()):
            if key not in allowed_filters:
                raise SkillCenterCorpusBM25Error(
                    f"unsupported BM25 filter: {key}"
                )
            clauses.append(f"d.{key} = ?")
            parameters.append(str(value))
        parameters.append(k)
        score_sql = (
            f"-bm25(documents_fts, {self.config.title_weight}, "
            f"{self.config.body_weight})"
        )
        sql = (
            "SELECT d.document_index, d.entry_cid, d.skill_id, d.title, "
            "d.domain, d.profile, d.repository_file, d.source_type, "
            "d.language, "
            + score_sql
            + " AS score FROM documents_fts "
            "JOIN documents AS d "
            "ON d.document_index = documents_fts.rowid - 1 WHERE "
            + " AND ".join(clauses)
            + " ORDER BY score DESC, d.entry_cid LIMIT ?"
        )
        rows = connection.execute(sql, parameters).fetchall()
        matched = (
            _matched_terms_by_document(
                connection,
                [int(row["document_index"]) + 1 for row in rows],
                terms,
            )
            if explain
            else {}
        )
        return tuple(
            SkillCenterCorpusBM25Hit(
                entry_cid=str(row["entry_cid"]),
                document_index=int(row["document_index"]),
                score=max(0.0, float(row["score"])),
                matched_terms=matched.get(
                    int(row["document_index"]) + 1, ()
                ),
                metadata={
                    "domain": str(row["domain"]),
                    "entry_cid": str(row["entry_cid"]),
                    "language": str(row["language"]),
                    "profile": str(row["profile"]),
                    "repository_file": str(row["repository_file"]),
                    "skill_id": str(row["skill_id"]),
                    "source_type": str(row["source_type"]),
                    "title": str(row["title"]),
                },
            )
            for row in rows
        )

    def entry_neighbors(
        self,
        entry_cid: str,
        *,
        k: int = 8,
        explain: bool = True,
    ) -> tuple[SkillCenterCorpusBM25Hit, ...]:
        validate_cid(entry_cid, path="/entry_cid")
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT title, domain, profile FROM documents "
                "WHERE entry_cid = ?",
                (entry_cid,),
            ).fetchone()
            if row is None:
                raise KeyError(entry_cid)
            terms = _neighbor_query_terms(str(row["title"]), self.config)
            return self._search_connection(
                connection,
                terms=terms,
                k=k,
                exclude_entry_cid=entry_cid,
                filters={"domain": str(row["domain"])},
                explain=explain,
                title_only=True,
            )

    def iter_entry_neighbors(
        self,
        *,
        k: int = 8,
        start_after: str = "",
        explain: bool = False,
    ) -> Iterator[
        tuple[str, tuple[SkillCenterCorpusBM25Hit, ...]]
    ]:
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            last_entry_cid = start_after
            while True:
                rows = connection.execute(
                    "SELECT entry_cid, title, domain, profile FROM documents "
                    "WHERE entry_cid > ? ORDER BY entry_cid LIMIT 256",
                    (last_entry_cid,),
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    normalized = str(row["entry_cid"])
                    terms = _neighbor_query_terms(
                        str(row["title"]),
                        self.config,
                    )
                    yield normalized, self._search_connection(
                        connection,
                        terms=terms,
                        k=k,
                        exclude_entry_cid=normalized,
                        filters={"domain": str(row["domain"])},
                        explain=explain,
                        title_only=True,
                    )
                    last_entry_cid = normalized

    def verify_corpus_coverage(self, corpus_dir: str | Path) -> None:
        corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
        expected_input = _corpus_input(corpus)
        if self.manifest.get("corpus_input") != expected_input:
            raise SkillCenterCorpusBM25Error(
                "BM25 index is not bound to this corpus manifest"
            )
        uri = f"{self.database_path.as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            indexed = {
                str(row[0])
                for row in connection.execute(
                    "SELECT entry_cid FROM documents"
                )
            }
        if indexed != corpus.entry_cids:
            raise SkillCenterCorpusBM25Error(
                "BM25 entry_cid coverage differs from canonical corpus"
            )


def build_skillcenter_corpus_bm25(
    corpus_dir: str | Path,
    *,
    output_dir: str | Path,
    config: SkillCenterCorpusBM25Config | None = None,
    batch_size: int = DEFAULT_BUILD_BATCH_SIZE,
) -> SkillCenterCorpusBM25BuildSummary:
    """Build a complete contentless FTS5 BM25 index from canonical Parquet."""

    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 10_000
    ):
        raise SkillCenterCorpusBM25Error(
            "batch_size must be between 1 and 10000"
        )
    active_config = config or SkillCenterCorpusBM25Config()
    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    corpus_input = _corpus_input(corpus)
    identity_payload = {
        "config": active_config.to_dict(),
        "corpus_input": corpus_input,
        "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
        "schema_version": SKILLCENTER_CORPUS_BM25_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(identity_payload)
    ).hexdigest()
    output = Path(output_dir).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise SkillCenterCorpusBM25Error("output_dir must not be a symlink")
    with _build_lock(output):
        if output.exists():
            existing = SkillCenterCorpusBM25Index.load(
                output,
                corpus_dir=corpus.root,
            )
            if (
                existing.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterCorpusBM25Error(
                    "existing BM25 index was built from different inputs"
                )
            return existing.summary
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.",
                suffix=".partial",
                dir=output.parent,
            )
        )
        try:
            _build_database(
                staging / "bm25.sqlite",
                corpus=corpus,
                batch_size=batch_size,
            )
            descriptor = _file_descriptor(
                staging / "bm25.sqlite",
                root=staging,
            )
            manifest = {
                "build_identity_sha256": build_identity_sha256,
                "config": active_config.to_dict(),
                "config_sha256": active_config.digest,
                "corpus_input": corpus_input,
                "dataset_id": corpus.manifest["dataset_id"],
                "dataset_revision": corpus.manifest["dataset_revision"],
                "indexed_entries": corpus.manifest["source_records"],
                "index_scope": "internal-retrieval-all-records",
                "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
                "schema_version": SKILLCENTER_CORPUS_BM25_SCHEMA_VERSION,
                "sqlite": descriptor,
            }
            _write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest),
            )
            os.replace(staging, output)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
    return SkillCenterCorpusBM25Index.load(
        output,
        corpus_dir=corpus.root,
    ).summary


def _build_database(
    path: Path,
    *,
    corpus: SkillCenterCorpusIndex,
    batch_size: int,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            PRAGMA temp_store = MEMORY;
            PRAGMA locking_mode = EXCLUSIVE;
            PRAGMA page_size = 32768;
            CREATE TABLE documents (
                entry_cid TEXT PRIMARY KEY,
                document_index INTEGER NOT NULL UNIQUE,
                skill_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                profile TEXT NOT NULL,
                repository_file TEXT NOT NULL,
                source_type TEXT NOT NULL,
                language TEXT NOT NULL,
                schema_version TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title,
                body,
                content='',
                columnsize=1,
                tokenize='unicode61 remove_diacritics 2'
            );
            CREATE VIRTUAL TABLE documents_vocab USING fts5vocab(
                documents_fts,
                'instance'
            );
            """
        )
        metadata_batch: list[tuple[Any, ...]] = []
        fts_batch: list[tuple[Any, ...]] = []
        columns = (
            "corpus_index",
            "domain",
            "entry_cid",
            "language",
            "profile",
            "repository_file",
            "skill_id",
            "skill_md",
            "source_type",
            "title",
        )
        connection.execute("BEGIN")
        for row in corpus.iter_rows(columns=columns, batch_size=batch_size):
            document_index = int(row["corpus_index"])
            metadata_batch.append(
                (
                    str(row["entry_cid"]),
                    document_index,
                    str(row["skill_id"]),
                    str(row["title"]),
                    str(row["domain"]),
                    str(row["profile"]),
                    str(row["repository_file"]),
                    str(row["source_type"]),
                    str(row["language"]),
                    SKILLCENTER_CORPUS_BM25_DOCUMENT_SCHEMA_VERSION,
                )
            )
            fts_batch.append(
                (
                    document_index + 1,
                    " ".join(
                        (
                            str(row["title"]),
                            str(row["domain"]),
                            str(row["profile"]),
                        )
                    ),
                    str(row["skill_md"]),
                )
            )
            if len(metadata_batch) >= batch_size:
                _insert_batches(connection, metadata_batch, fts_batch)
                metadata_batch.clear()
                fts_batch.clear()
        if metadata_batch:
            _insert_batches(connection, metadata_batch, fts_batch)
        connection.commit()
        connection.execute(
            "INSERT INTO documents_fts(documents_fts) VALUES('optimize')"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _insert_batches(
    connection: sqlite3.Connection,
    metadata: Sequence[tuple[Any, ...]],
    fts: Sequence[tuple[Any, ...]],
) -> None:
    connection.executemany(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        metadata,
    )
    connection.executemany(
        "INSERT INTO documents_fts(rowid, title, body) VALUES (?, ?, ?)",
        fts,
    )


def _query_terms(
    query: str,
    config: SkillCenterCorpusBM25Config,
) -> tuple[str, ...]:
    seen: set[str] = set()
    output = []
    for term in tokenize_lexical_text(str(query or "")):
        if term in seen:
            continue
        seen.add(term)
        output.append(term)
        if len(output) >= config.max_query_terms:
            break
    return tuple(output)


_NEIGHBOR_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "agent",
        "agents",
        "also",
        "and",
        "are",
        "build",
        "create",
        "for",
        "from",
        "how",
        "into",
        "skill",
        "skills",
        "that",
        "the",
        "this",
        "use",
        "using",
        "when",
        "with",
        "your",
    }
)


def _neighbor_query_terms(
    title: str,
    config: SkillCenterCorpusBM25Config,
) -> tuple[str, ...]:
    candidates = {
        term
        for term in tokenize_lexical_text(str(title or ""))
        if len(term) >= 3 and term not in _NEIGHBOR_STOPWORDS
    }
    ranked = sorted(candidates, key=lambda term: (-len(term), term))
    if not ranked:
        ranked = list(_query_terms(title, config))
    return tuple(ranked[: min(config.max_query_terms, 8)])


def _quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _matched_terms_by_document(
    connection: sqlite3.Connection,
    document_ids: Sequence[int],
    terms: Sequence[str],
) -> dict[int, tuple[str, ...]]:
    if not document_ids or not terms:
        return {}
    document_placeholders = ",".join("?" for _ in document_ids)
    term_placeholders = ",".join("?" for _ in terms)
    sql = (
        "SELECT DISTINCT doc, term FROM documents_vocab WHERE doc IN ("
        + document_placeholders
        + ") AND term IN ("
        + term_placeholders
        + ") ORDER BY doc, term"
    )
    grouped: dict[int, list[str]] = {}
    for document_id, term in connection.execute(
        sql,
        [*document_ids, *terms],
    ):
        grouped.setdefault(int(document_id), []).append(str(term))
    return {
        document_id: tuple(values)
        for document_id, values in grouped.items()
    }


def _corpus_input(corpus: SkillCenterCorpusIndex) -> dict[str, Any]:
    manifest_bytes = (corpus.root / "manifest.json").read_bytes()
    corpus_file = corpus.manifest["files"]["corpus"]
    return {
        "corpus_cid": str(corpus_file["cid"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "primary_key": str(corpus.manifest["primary_key"]),
        "source_records": int(corpus.manifest["source_records"]),
        "unique_entry_cids": int(corpus.manifest["unique_entry_cids"]),
    }


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    size_bytes, digest = _file_digest(path)
    return {
        "cid": cid_v1_from_digest(digest),
        "media_type": "application/vnd.sqlite3",
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }


def _verify_file_descriptor(root: Path, value: Any) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterCorpusBM25Error("SQLite descriptor is missing")
    relative = value.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise SkillCenterCorpusBM25Error("SQLite descriptor path is missing")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise SkillCenterCorpusBM25Error("SQLite descriptor path is unsafe")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise SkillCenterCorpusBM25Error("BM25 SQLite artifact is missing")
    size_bytes, digest = _file_digest(path)
    if (
        size_bytes != int(value.get("size_bytes", -1))
        or digest.hex() != value.get("sha256")
        or cid_v1_from_digest(digest) != value.get("cid")
    ):
        raise SkillCenterCorpusBM25Error(
            "BM25 SQLite artifact identity mismatch"
        )
    return path


def _file_digest(path: Path) -> tuple[int, bytes]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            size_bytes += len(chunk)
            digest.update(chunk)
    return size_bytes, digest.digest()


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _build_lock(output: Path) -> Iterator[None]:
    import fcntl

    lock_path = output.parent / f".{output.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        pass


__all__ = [
    "DEFAULT_BODY_WEIGHT",
    "DEFAULT_MAX_QUERY_TERMS",
    "DEFAULT_TITLE_WEIGHT",
    "SKILLCENTER_CORPUS_BM25_SCHEMA_VERSION",
    "SkillCenterCorpusBM25BuildSummary",
    "SkillCenterCorpusBM25Config",
    "SkillCenterCorpusBM25Error",
    "SkillCenterCorpusBM25Hit",
    "SkillCenterCorpusBM25Index",
    "build_skillcenter_corpus_bm25",
]
