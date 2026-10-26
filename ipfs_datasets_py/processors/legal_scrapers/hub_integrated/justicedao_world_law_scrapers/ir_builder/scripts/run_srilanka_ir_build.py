#!/usr/bin/env python3
"""Build Sri Lanka IR from filtered tip b0a6e3a60f32 with real gte-small.

Prefer SQLite FTS5 streaming neighbors for ~50k corpus (DO OOM lesson);
fall back to stock bm25_neighbors only if corpus is small or SQLite fails
and MemAvailable stays high.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gc, json, os, pickle, sqlite3, sys, traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")
sys.path.insert(0, "/workspace/ipfs_datasets_py_pull")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from country_laws_ir.bm25 import bm25_neighbors, build_index
from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.catalog import get_country, target_repo
from country_laws_ir.graph import build_graph
from country_laws_ir.normalize import build_corpus, load_source
from country_laws_ir.package import package_release
from country_laws_ir.tokenize import tokenize
from country_laws_ir.vectors import encode_corpus, embeddings_available, layout_vectors

SRC = Path("/workspace/country-laws-ir/cache/srilanka_filtered_b0a6e3a60f32")
OUT = Path("/workspace/country-laws-ir/releases/ipfs_srilanka_laws_ir")
CKPT = CACHE / "embeddings" / "srilanka.npy"
CORPUS_CKPT = CACHE / "srilanka_corpus_b0a6e3a60f32.parquet"
SPILL = CACHE / "srilanka_bm25_spill"
SQLITE_PATH = SPILL / "srilanka_fts.sqlite"
LOG = Path("/workspace/country-laws-ir/reports/srilanka_build_b0a6e3a60f32.log")
TIP = "b0a6e3a60f32ed4f0c04c7d7a81b174e1cb3cd9e"
TIP_SHORT = "b0a6e3a60f32"
WARN_GIB = 3.5
SQLITE_THRESHOLD = 40000
BATCH = 256
SHARD = 5000
NEIGHBOR_K = 8
TITLE_W = 5.0
BODY_W = 1.0
DF_CAP = 1500
MAX_QTERMS = 8

# Collector shed order if MemAvailable drops during embed: MM / IS-reg / TH before IT/AT/DK
COLLECTOR_SHED_ORDER = [
    ("mm", [184652, 184631]),
    ("is-reg", [260505, 260498]),
    ("th", []),  # live PIDs refreshed at shed time
    ("dk", [68137, 68130]),
    ("it_deepen", [228586]),  # protect last
    ("at_deepen", [67996]),    # protect last
]
SIGTERM_NOTES: list[dict] = []

def mem_gib() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    return -1.0


def rss_gib() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return -1.0


def maybe_shed_collectors(stage: str) -> None:
    g = mem_gib()
    if 0 <= g < WARN_GIB:
        _log(f"MEM_WARN stage={stage} mem={g:.2f}G")
    else:
        _log(f"mem_ok stage={stage} mem={g:.2f}G")

def spill_pickle(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_pickle(path: Path):
    with path.open("rb") as f:
        return pickle.load(f)


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_sqlite_fts(corpus_path: Path, db_path: Path, expected: int) -> int:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            PRAGMA temp_store = MEMORY;
            PRAGMA locking_mode = EXCLUSIVE;
            PRAGMA page_size = 32768;
            CREATE TABLE documents (
                document_index INTEGER PRIMARY KEY,
                entry_cid TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                query_text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title,
                body,
                content='',
                columnsize=1,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        pf = pq.ParquetFile(corpus_path)
        n = 0
        meta_batch: list[tuple] = []
        fts_batch: list[tuple] = []
        conn.execute("BEGIN")
        for batch in pf.iter_batches(
            batch_size=BATCH, columns=["document_index", "entry_cid", "title", "body"]
        ):
            cols = batch.to_pydict()
            for i in range(len(cols["document_index"])):
                di = int(cols["document_index"][i])
                title = str(cols["title"][i] or "")
                body = str(cols["body"][i] or "")
                cid = str(cols["entry_cid"][i])
                qtext = title.strip() if title.strip() else body[:800]
                meta_batch.append((di, cid, title, qtext))
                fts_batch.append((di + 1, title, body))
                if len(meta_batch) >= BATCH:
                    conn.executemany(
                        "INSERT INTO documents(document_index, entry_cid, title, query_text) "
                        "VALUES (?,?,?,?)",
                        meta_batch,
                    )
                    conn.executemany(
                        "INSERT INTO documents_fts(rowid, title, body) VALUES (?,?,?)",
                        fts_batch,
                    )
                    n += len(meta_batch)
                    meta_batch.clear()
                    fts_batch.clear()
                    if n % 20000 == 0:
                        _log(f"fts insert {n} mem={mem_gib():.2f}G rss={rss_gib():.2f}G")
                        maybe_shed_collectors("fts_insert")
                        gc.collect()
        if meta_batch:
            conn.executemany(
                "INSERT INTO documents(document_index, entry_cid, title, query_text) "
                "VALUES (?,?,?,?)",
                meta_batch,
            )
            conn.executemany(
                "INSERT INTO documents_fts(rowid, title, body) VALUES (?,?,?)",
                fts_batch,
            )
            n += len(meta_batch)
        conn.commit()
        conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('optimize')")
        conn.commit()
        conn.execute(
            "CREATE VIRTUAL TABLE documents_vocab USING fts5vocab(documents_fts, 'row')"
        )
        conn.commit()
        got = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        assert got == n == expected, (got, n, expected)
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        gc.collect()


def load_df_map(conn: sqlite3.Connection, df_cap: int) -> dict[str, int]:
    _log(f"loading vocab df_cap={df_cap} mem={mem_gib():.2f}G")
    df_map: dict[str, int] = {}
    for term, doc in conn.execute(
        "SELECT term, doc FROM documents_vocab WHERE doc <= ?", (df_cap,)
    ):
        df_map[str(term)] = int(doc)
    _log(f"vocab rare_terms={len(df_map)} mem={mem_gib():.2f}G rss={rss_gib():.2f}G")
    return df_map


def select_query_terms(query_text: str, df_map: dict[str, int]) -> list[str]:
    toks = tokenize(query_text)[:24]
    seen = set()
    cands = []
    for t in toks:
        if t in seen or len(t) < 2:
            continue
        seen.add(t)
        if t not in df_map:
            continue
        cands.append((df_map[t], t))
    cands.sort()
    return [t for _, t in cands[:MAX_QTERMS]]


def stream_neighbors_to_shards(db_path: Path, n_docs: int, k: int) -> list[Path]:
    conn_rw = sqlite3.connect(str(db_path))
    row = conn_rw.execute(
        "SELECT name FROM sqlite_master WHERE name='documents_vocab'"
    ).fetchone()
    if row is None:
        conn_rw.execute(
            "CREATE VIRTUAL TABLE documents_vocab USING fts5vocab(documents_fts, 'row')"
        )
        conn_rw.commit()
    df_map = load_df_map(conn_rw, DF_CAP)
    conn_rw.close()
    spill_pickle(SPILL / "df_map_meta.pkl", {"n_rare": len(df_map), "df_cap": DF_CAP})

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    shard_paths: list[Path] = []
    buf: list = []
    buf_start = 0
    done = 0
    score_sql = f"-bm25(documents_fts, {TITLE_W}, {BODY_W})"
    try:
        last_idx = -1
        while True:
            rows = conn.execute(
                "SELECT document_index, entry_cid, query_text FROM documents "
                "WHERE document_index > ? ORDER BY document_index LIMIT ?",
                (last_idx, BATCH),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                di = int(row["document_index"])
                terms = select_query_terms(str(row["query_text"]), df_map)
                if not terms:
                    neigh: list = []
                else:
                    expr = " OR ".join("title : " + quote_fts_term(t) for t in terms)
                    sql = (
                        "SELECT d.document_index, " + score_sql + " AS score "
                        "FROM documents_fts "
                        "JOIN documents AS d ON d.document_index = documents_fts.rowid - 1 "
                        "WHERE documents_fts MATCH ? AND d.document_index != ? "
                        "ORDER BY score DESC, d.document_index LIMIT ?"
                    )
                    hits = conn.execute(sql, (expr, di, k)).fetchall()
                    neigh = [
                        (int(h["document_index"]), max(0.0, float(h["score"])), list(terms)[:4])
                        for h in hits
                    ]
                while buf_start + len(buf) < di:
                    buf.append([])
                buf.append(neigh)
                last_idx = di
                done += 1
                if len(buf) >= SHARD:
                    end = buf_start + len(buf)
                    sp = SPILL / f"neighbors_{buf_start:06d}_{end:06d}.pkl"
                    spill_pickle(sp, buf)
                    shard_paths.append(sp)
                    _log(
                        f"neighbors shard {buf_start}:{end}/{n_docs} "
                        f"mem={mem_gib():.2f}G rss={rss_gib():.2f}G"
                    )
                    buf_start = end
                    buf = []
                    gc.collect()
                    maybe_shed_collectors("neighbors")
                if done % 5000 == 0:
                    print(
                        f"bm25 neighbors streamed {done}/{n_docs} "
                        f"mem={mem_gib():.2f}G rss={rss_gib():.2f}G",
                        flush=True,
                    )
        if buf:
            end = buf_start + len(buf)
            sp = SPILL / f"neighbors_{buf_start:06d}_{end:06d}.pkl"
            spill_pickle(sp, buf)
            shard_paths.append(sp)
            _log(f"neighbors shard final {buf_start}:{end}/{n_docs}")
        print(f"bm25 neighbors {done}/{n_docs}", flush=True)
        return shard_paths
    finally:
        conn.close()
        del df_map
        gc.collect()


def assemble_neighbors(shard_paths: list[Path], n_docs: int) -> list:
    neighbors: list = []
    for sp in shard_paths:
        neighbors.extend(load_pickle(sp))
    while len(neighbors) < n_docs:
        neighbors.append([])
    if len(neighbors) > n_docs:
        neighbors = neighbors[:n_docs]
    return neighbors


def neighbors_via_sqlite(n_docs: int) -> list:
    SPILL.mkdir(parents=True, exist_ok=True)
    for p in SPILL.glob("neighbors_*.pkl"):
        p.unlink()
    if SQLITE_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
            got = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            conn.close()
            if got != n_docs:
                SQLITE_PATH.unlink()
        except Exception:
            if SQLITE_PATH.exists():
                SQLITE_PATH.unlink()
    if not SQLITE_PATH.exists():
        build_sqlite_fts(CORPUS_CKPT, SQLITE_PATH, n_docs)
    shards = stream_neighbors_to_shards(SQLITE_PATH, n_docs, NEIGHBOR_K)
    return assemble_neighbors(shards, n_docs)


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_f = LOG.open("w", encoding="utf-8")

    class Tee:
        def write(self, d):
            sys.__stdout__.write(d)
            sys.__stdout__.flush()
            log_f.write(d)
            log_f.flush()

        def flush(self):
            sys.__stdout__.flush()
            log_f.flush()

    sys.stdout = Tee()
    sys.stderr = Tee()

    neighbor_via = None
    try:
        g = mem_gib()
        _log(f"srilanka build start mem={g:.2f}G emb_avail={embeddings_available()}")
        if not embeddings_available():
            raise SystemExit("torch/ST unavailable — refusing stub vectors")
        if 0 <= g < WARN_GIB:
            maybe_shed_collectors("start")
            g = mem_gib()
            if 0 <= g < WARN_GIB:
                raise SystemExit(f"PAUSED_MEM at start mem={g:.2f}G")
        if not SRC.is_dir():
            raise SystemExit(f"missing filtered pack {SRC}")

        country = get_country(str(SRC))
        laws, articles, source_meta = load_source(str(SRC), CACHE)
        if not (source_meta.get("source_revision") or "").startswith(TIP_SHORT):
            source_meta["source_revision"] = TIP
        _log(
            f"source loaded laws={source_meta['n_laws_source']} "
            f"articles={source_meta['n_articles_source']} rev={source_meta['source_revision']}"
        )
        corpus, norm_report = build_corpus(laws, articles, source_meta)
        del laws, articles
        gc.collect()
        CORPUS_CKPT.parent.mkdir(parents=True, exist_ok=True)
        corpus.to_parquet(CORPUS_CKPT, index=False)
        (REPORTS / "srilanka_normalization.json").write_text(
            json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _log(f"corpus n={len(corpus)} dropped={norm_report.get('n_dropped_total')} mem={mem_gib():.2f}G")

        g = mem_gib()
        if 0 <= g < WARN_GIB:
            maybe_shed_collectors("before_encode")
            g = mem_gib()
            if 0 <= g < WARN_GIB:
                raise SystemExit(f"PAUSED_MEM before encode mem={g:.2f}G")

        CKPT.parent.mkdir(parents=True, exist_ok=True)
        _log(f"encode start checkpoint={CKPT}")
        emb = encode_corpus(corpus, device="cpu", checkpoint_path=str(CKPT))
        assert emb.shape[0] == len(corpus), (emb.shape, len(corpus))
        vectors = layout_vectors(corpus, emb)
        del emb
        gc.collect()
        _log(f"vectors n={vectors['stats']['n_vectors']} mem={mem_gib():.2f}G")

        g = mem_gib()
        if 0 <= g < WARN_GIB:
            maybe_shed_collectors("before_bm25")
            g = mem_gib()
            if 0 <= g < WARN_GIB:
                raise SystemExit(f"PAUSED_MEM before bm25 mem={g:.2f}G")

        bm25 = build_index(corpus)
        _log(f"bm25 terms={bm25['stats']['n_terms']} postings={bm25['stats']['n_postings']}")

        n = len(corpus)
        # Prefer SQLite streaming for ~50k (DO OOM lesson)
        if n >= SQLITE_THRESHOLD:
            _log(f"prefer sqlite neighbors n={n} (>= {SQLITE_THRESHOLD})")
            # free heavy in-memory maps before SQLite path; rebuild maps not needed for neighbors
            # keep bm25 documents/postings/stats for package
            try:
                # drop postings_map / toks if present to free RAM
                for k in ("postings_map", "title_toks", "body_toks", "idf", "doc_len"):
                    bm25.pop(k, None)
                gc.collect()
                neighbors = neighbors_via_sqlite(n)
                neighbor_via = "sqlite_fts"
            except Exception as exc:
                _log(f"sqlite neighbors failed ({type(exc).__name__}: {exc}); trying stock")
                traceback.print_exc()
                # rebuild index for stock path
                bm25 = build_index(corpus)
                neighbors = bm25_neighbors(bm25, k=NEIGHBOR_K)
                neighbor_via = "stock_fallback"
        else:
            try:
                neighbors = bm25_neighbors(bm25, k=NEIGHBOR_K)
                neighbor_via = "stock"
            except Exception as exc:
                _log(f"stock bm25_neighbors failed ({exc}); sqlite spill")
                neighbors = neighbors_via_sqlite(n)
                neighbor_via = "sqlite_fts_fallback"

        graph = build_graph(corpus, neighbors)
        del neighbors
        gc.collect()
        _log(
            f"graph nodes={graph['stats']['n_nodes']} edges={graph['stats']['n_edges']} "
            f"via={neighbor_via} mem={mem_gib():.2f}G"
        )

        manifest = package_release(
            OUT,
            corpus,
            bm25,
            graph,
            vectors,
            source_meta,
            country,
            Path("/workspace/country-laws-ir"),
            normalization_report=norm_report,
        )
        result = {
            "country": country["slug"],
            "source": country["repo"],
            "source_revision": source_meta.get("source_revision"),
            "out": str(OUT),
            "target_hub_id": target_repo(country["slug"]),
            "counts": manifest.get("counts"),
            "vector_blocker": None,
            "vector_status": (manifest.get("vector") or {}).get("status") or "embedded",
            "schema_version": manifest.get("schema_version"),
            "mem_end_gib": round(mem_gib(), 2),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": f"srilanka_build_filter_embed_package_{neighbor_via}",
            "neighbor_via": neighbor_via,
            "normalization_drops": norm_report.get("drops"),
            "n_dropped_total": norm_report.get("n_dropped_total"),
            "collectors_sigterm": SIGTERM_NOTES,
        }
        record_progress({"event": "built_local", **{k: result[k] for k in result if k != "counts"}})
        (REPORTS / "srilanka_build_b0a6e3a60f32_result.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
