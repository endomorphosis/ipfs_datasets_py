"""DuckDB views over country-laws sparse GraphRAG parquet shards.

Published artifacts are ZSTD parquet (SkillCenter / publicus-ir family).
Query and large-corpus neighbor generation read those shards through DuckDB
instead of loading them into pandas or SQLite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

K1 = 1.2
B = 0.75
TITLE_WEIGHT = 5.0
BODY_WEIGHT = 1.0
MAX_QUERY_TERMS = 64

VIEWS = (
    ("corpus", "data/corpus/*.parquet"),
    ("bm25_documents", "data/bm25/documents/*.parquet"),
    ("bm25_postings", "data/bm25/postings/*.parquet"),
    ("graph_nodes", "data/graph/nodes/*.parquet"),
    ("graph_edges", "data/graph/edges/*.parquet"),
    # Shared hf_graphrag layout (US Code / state laws / FR).
    ("graph_in", "data/graph/adjacency/in/*.parquet"),
    ("graph_out", "data/graph/adjacency/out/*.parquet"),
    # Legacy country-laws-ir layout still on some Hub packs.
    ("graph_incoming", "data/graph/adjacency/incoming/*.parquet"),
    ("graph_outgoing", "data/graph/adjacency/outgoing/*.parquet"),
    ("vectors", "data/vectors/*.parquet"),
)


class DuckDBStoreError(RuntimeError):
    """Raised when a parquet/DuckDB sparse index cannot be opened."""


def _require_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise DuckDBStoreError("duckdb is required for parquet sparse GraphRAG query") from exc
    return duckdb


def parquet_glob(root: Path, pattern: str) -> str:
    return str(Path(root) / pattern)


def connect_release(root: Path, *, database: str = ":memory:"):
    """Open a DuckDB connection with views over parquet shards."""
    duckdb = _require_duckdb()
    root = Path(root)
    if not (root / "manifest.json").is_file():
        raise DuckDBStoreError(f"release missing manifest.json: {root}")
    con = duckdb.connect(database)
    for name, pattern in VIEWS:
        glob = parquet_glob(root, pattern)
        if list(root.glob(pattern)):
            escaped = glob.replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{escaped}')"
            )
    return con


def load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))


def tokenize(text: str) -> list[str]:
    import re
    import unicodedata

    if not text:
        return []
    nfkd = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()
    return re.findall(r"[0-9A-Za-z]+", folded)


def bm25_search(root: Path, query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Okapi BM25 over parquet posting shards via DuckDB UNNEST."""
    terms = tokenize(query)[:MAX_QUERY_TERMS]
    if not terms:
        return []
    manifest = load_manifest(root)
    avgdl = float((manifest.get("bm25") or {}).get("average_document_length") or 1.0) or 1.0
    con = connect_release(root)
    try:
        tables = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        if "bm25_postings" not in tables or "bm25_documents" not in tables:
            raise DuckDBStoreError("release is missing BM25 parquet shards")
        placeholders = ", ".join(["?"] * len(terms))
        sql = f"""
            WITH exploded AS (
                SELECT
                    unnest(document_indices) AS document_index,
                    unnest(title_frequencies) AS title_tf,
                    unnest(body_frequencies) AS body_tf,
                    unnest(document_lengths) AS dl,
                    idf
                FROM bm25_postings
                WHERE term IN ({placeholders})
            ),
            scored AS (
                SELECT
                    document_index,
                    SUM(
                        idf * (
                            ( {TITLE_WEIGHT} * title_tf + {BODY_WEIGHT} * body_tf )
                            * ({K1} + 1.0)
                        ) / (
                            ( {TITLE_WEIGHT} * title_tf + {BODY_WEIGHT} * body_tf )
                            + {K1} * (1.0 - {B} + {B} * (dl / {avgdl}))
                        )
                    ) AS score
                FROM exploded
                GROUP BY document_index
            )
            SELECT
                s.document_index,
                s.score,
                d.entry_cid,
                d.title,
                d.record_type
            FROM scored s
            JOIN bm25_documents d USING (document_index)
            ORDER BY s.score DESC, s.document_index
            LIMIT ?
        """
        rows = con.execute(sql, [*terms, int(top_k)]).fetchall()
        cols = [
            "document_index",
            "score",
            "entry_cid",
            "title",
            "record_type",
        ]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        con.close()


def cite_search(
    root: Path,
    citation: str,
    *,
    cite_format: str = "any",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Look up corpus rows by Bluebook, official cite, or normalized cite_key."""
    from .citations import normalize_cite_key

    needle = (citation or "").strip()
    if not needle:
        return []
    key = normalize_cite_key(needle)
    con = connect_release(root)
    try:
        tables = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        if "corpus" not in tables:
            raise DuckDBStoreError("release is missing corpus parquet shards")
        cols = [
            r[1]
            for r in con.execute(
                "SELECT table_schema, column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = 'corpus'"
            ).fetchall()
        ]
        wanted = [
            "entry_cid",
            "record_type",
            "title",
            "instrument_title",
            "article_number",
            "official_citation",
            "bluebook_citation",
            "cite_key",
            "citation_status",
            "source_url",
        ]
        select = ", ".join(c for c in wanted if c in cols) or "*"
        clauses = []
        params: list[Any] = []
        fmt = (cite_format or "any").strip().lower()
        if fmt in {"any", "bluebook"} and "bluebook_citation" in cols:
            clauses.append("lower(coalesce(bluebook_citation, '')) = lower(?)")
            params.append(needle)
        if fmt in {"any", "official"} and "official_citation" in cols:
            clauses.append("lower(coalesce(official_citation, '')) = lower(?)")
            params.append(needle)
        if "cite_key" in cols and key:
            clauses.append("cite_key = ?")
            params.append(key)
        if not clauses:
            return []
        sql = f"SELECT {select} FROM corpus WHERE {' OR '.join(clauses)} LIMIT ?"
        params.append(int(limit))
        rows = con.execute(sql, params).fetchall()
        names = [c for c in wanted if c in cols] if select != "*" else list(cols)
        return [dict(zip(names, row)) for row in rows]
    finally:
        con.close()


def graph_neighbors(
    root: Path,
    node_cid: str,
    *,
    direction: str = "both",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Adjacency lookup over parquet shards via DuckDB."""
    aliases = {
        "both": ("in", "out", "incoming", "outgoing"),
        "in": ("in", "incoming"),
        "out": ("out", "outgoing"),
        "incoming": ("in", "incoming"),
        "outgoing": ("out", "outgoing"),
    }
    dirs = aliases.get(direction, (direction,))
    con = connect_release(root)
    try:
        tables = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        hits: list[dict[str, Any]] = []
        for d in dirs:
            view = {
                "in": "graph_in",
                "out": "graph_out",
                "incoming": "graph_incoming",
                "outgoing": "graph_outgoing",
            }.get(d, d)
            if view not in tables:
                continue
            rows = con.execute(
                f"""
                SELECT node_cid, neighbor_cids, edge_types, scores
                FROM {view}
                WHERE node_cid = ?
                """,
                [node_cid],
            ).fetchall()
            for node, neighs, types, scores in rows:
                neighs = list(neighs or [])
                types = list(types or [])
                scores = list(scores or [])
                for i, neigh in enumerate(neighs):
                    hits.append(
                        {
                            "direction": d,
                            "node_cid": node,
                            "neighbor_cid": neigh,
                            "edge_type": types[i] if i < len(types) else "",
                            "score": scores[i] if i < len(scores) else None,
                        }
                    )
        hits.sort(key=lambda r: (-(r["score"] or 0), str(r["neighbor_cid"])))
        return hits[: int(limit)]
    finally:
        con.close()


def build_fts_index(
    corpus_parquet: Path,
    duckdb_path: Path,
    expected: int,
    *,
    log: Any | None = None,
) -> Path:
    """Load corpus parquet into DuckDB and create an FTS index (no SQLite)."""
    duckdb = _require_duckdb()
    duckdb_path = Path(duckdb_path)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    if duckdb_path.exists():
        duckdb_path.unlink()
    escaped = str(Path(corpus_parquet).resolve()).replace("'", "''")
    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute(
            f"""
            CREATE TABLE documents AS
            SELECT
                CAST(document_index AS INTEGER) AS document_index,
                CAST(entry_cid AS VARCHAR) AS entry_cid,
                CAST(COALESCE(title, '') AS VARCHAR) AS title,
                CAST(COALESCE(body, '') AS VARCHAR) AS body
            FROM read_parquet('{escaped}')
            """
        )
        n = int(con.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        if n != int(expected):
            raise DuckDBStoreError(f"DuckDB corpus rows {n} != expected {expected}")
        con.execute("INSTALL fts")
        con.execute("LOAD fts")
        con.execute(
            "PRAGMA create_fts_index('documents', 'document_index', 'title', 'body', "
            "stemmer='porter', stopwords='english', ignore='(\\.+)', strip_accents=1, lower=1)"
        )
        if log:
            log(f"duckdb fts ready n={n} path={duckdb_path}")
    finally:
        con.close()
    return duckdb_path


def stream_neighbors_to_parquet(
    duckdb_path: Path,
    spill: Path,
    n_docs: int,
    *,
    k: int = 8,
    shard: int = 5000,
    batch: int = 256,
    resume: bool = True,
    log: Any | None = None,
) -> list[Path]:
    """Stream DuckDB FTS neighbors into flattened neighbor_*.parquet shards."""
    duckdb = _require_duckdb()
    spill = Path(spill)
    spill.mkdir(parents=True, exist_ok=True)
    existing = sorted(spill.glob("neighbors_*.parquet"))
    buf_start = 0
    shard_paths: list[Path] = []
    if resume and existing:
        covered = 0
        for path in existing:
            parts = path.stem.split("_")
            try:
                start_i, end_i = int(parts[1]), int(parts[2])
            except (IndexError, ValueError):
                continue
            if start_i != covered:
                break
            shard_paths.append(path)
            covered = end_i
        buf_start = covered
        if buf_start >= n_docs:
            if log:
                log(f"neighbors resume complete {buf_start}/{n_docs}")
            return shard_paths
        for path in existing:
            if path not in shard_paths:
                path.unlink(missing_ok=True)
    else:
        for path in existing:
            path.unlink(missing_ok=True)

    con = duckdb.connect(str(duckdb_path), read_only=True)
    con.execute("LOAD fts")
    rows_buf: list[dict[str, Any]] = []
    shard_start = buf_start
    last_idx = buf_start - 1
    done = buf_start
    try:
        while True:
            batch_rows = con.execute(
                "SELECT document_index, title, body FROM documents "
                "WHERE document_index > ? ORDER BY document_index LIMIT ?",
                [last_idx, batch],
            ).fetchall()
            if not batch_rows:
                break
            for di, title, body in batch_rows:
                di = int(di)
                query = (str(title or "").strip() or str(body or "")[:800]).strip()
                hits: list[tuple[int, float]] = []
                if query:
                    hits = con.execute(
                        "SELECT document_index, "
                        "fts_main_documents.match_bm25(document_index, ?) AS score "
                        "FROM documents "
                        "WHERE document_index != ? AND score IS NOT NULL "
                        "ORDER BY score DESC, document_index "
                        "LIMIT ?",
                        [query, di, int(k)],
                    ).fetchall()
                for neigh_i, score in hits:
                    rows_buf.append(
                        {
                            "source_index": di,
                            "neighbor_index": int(neigh_i),
                            "score": float(score or 0.0),
                        }
                    )
                last_idx = di
                done += 1
                if (di + 1 - shard_start) >= shard:
                    end = di + 1
                    path = spill / f"neighbors_{shard_start:06d}_{end:06d}.parquet"
                    pd.DataFrame(rows_buf).to_parquet(path, index=False)
                    shard_paths.append(path)
                    rows_buf = []
                    shard_start = end
                    if log:
                        log(f"neighbors parquet shard {path.name}")
            if done % 5_000 == 0 and log:
                log(f"duckdb neighbors {done}/{n_docs}")
        if shard_start < n_docs:
            path = spill / f"neighbors_{shard_start:06d}_{n_docs:06d}.parquet"
            pd.DataFrame(rows_buf).to_parquet(path, index=False)
            shard_paths.append(path)
        if log:
            log(f"duckdb neighbors done={done} shards={len(shard_paths)}")
        return shard_paths
    finally:
        con.close()


def iter_neighbor_parquet_shards(spill: Path) -> Any:
    """Yield (start_index, list-of-neighbor-lists) from parquet shards."""
    import pandas as pd

    paths = sorted(Path(spill).glob("neighbors_*.parquet"))
    for path in paths:
        parts = path.stem.split("_")
        start_i = int(parts[1])
        end_i = int(parts[2])
        frame = pd.read_parquet(path)
        part: list[list] = [[] for _ in range(max(0, end_i - start_i))]
        if not frame.empty:
            for rec in frame.itertuples(index=False):
                src = int(rec.source_index)
                offset = src - start_i
                if 0 <= offset < len(part):
                    part[offset].append(
                        (int(rec.neighbor_index), float(rec.score), [])
                    )
        yield start_i, part


def materialize_corpus_duckdb(corpus_parquet: Path, duckdb_path: Path) -> Path:
    """Load a corpus parquet file into a persistent DuckDB database."""
    duckdb = _require_duckdb()
    duckdb_path = Path(duckdb_path)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    if duckdb_path.exists():
        duckdb_path.unlink()
    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute(
            """
            CREATE TABLE documents AS
            SELECT
                CAST(document_index AS INTEGER) AS document_index,
                CAST(entry_cid AS VARCHAR) AS entry_cid,
                CAST(title AS VARCHAR) AS title,
                CAST(body AS VARCHAR) AS body
            FROM read_parquet(?)
            """,
            [str(corpus_parquet)],
        )
        con.execute("CREATE INDEX documents_idx ON documents(document_index)")
    finally:
        con.close()
    return duckdb_path
