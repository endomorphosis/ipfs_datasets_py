"""Okapi BM25 (k1=1.2, b=0.75, title_weight=5, body_weight=1) + posting shards."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np
import pandas as pd

from . import MAX_ROWS_PER_FILE, SCHEMA_VERSION
from .tokenize import tokenize

K1 = 1.2
B = 0.75
TITLE_WEIGHT = 5.0
BODY_WEIGHT = 1.0
POSTING_ROWS_PER_RECORD = 4096
TERMS_PER_SHARD = 4096
MAX_QUERY_TERMS = 64


def _idf(n_docs: int, df: int) -> float:
    # rank_bm25 Okapi: ln((N - df + 0.5) / (df + 0.5) + 1)
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def build_index(corpus: pd.DataFrame) -> dict[str, Any]:
    n = len(corpus)
    titles = corpus["title"].fillna("").astype(str).tolist()
    bodies = corpus["body"].fillna("").astype(str).tolist()
    title_toks = [tokenize(t) for t in titles]
    body_toks = [tokenize(t) for t in bodies]

    title_len = np.array([len(t) for t in title_toks], dtype=np.int32)
    body_len = np.array([len(t) for t in body_toks], dtype=np.int32)
    doc_len = (title_len * TITLE_WEIGHT + body_len * BODY_WEIGHT).astype(np.float64)
    avgdl = float(doc_len.mean()) if n else 0.0

    # term -> {doc: [title_tf, body_tf]}
    postings: dict[str, dict[int, list[int]]] = defaultdict(dict)
    for i, (tt, bt) in enumerate(zip(title_toks, body_toks)):
        tf_t: dict[str, int] = defaultdict(int)
        tf_b: dict[str, int] = defaultdict(int)
        for tok in tt:
            tf_t[tok] += 1
        for tok in bt:
            tf_b[tok] += 1
        for tok in set(tf_t) | set(tf_b):
            postings[tok][i] = [int(tf_t.get(tok, 0)), int(tf_b.get(tok, 0))]

    terms = sorted(postings)
    idf = {t: _idf(n, len(postings[t])) for t in terms}

    doc_rows = []
    for i, row in corpus.iterrows():
        idx = int(row["document_index"])
        doc_rows.append(
            {
                "entry_cid": row["entry_cid"],
                "document_index": idx,
                "law_id": row["law_id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "record_type": row["record_type"],
                "language": row.get("language", ""),
                "source_type": row.get("source_type", ""),
                "jurisdiction": row.get("jurisdiction", ""),
                "title_length": int(title_len[idx]),
                "body_length": int(body_len[idx]),
                "document_length": int(round(doc_len[idx])),
                "schema_version": SCHEMA_VERSION,
            }
        )
    documents = pd.DataFrame(doc_rows).sort_values("document_index").reset_index(drop=True)

    posting_rows = []
    for term in terms:
        items = sorted(postings[term].items())
        chunks = [
            items[i : i + POSTING_ROWS_PER_RECORD]
            for i in range(0, max(len(items), 1), POSTING_ROWS_PER_RECORD)
        ]
        n_chunks = len(chunks)
        dfreq = len(items)
        cfreq = sum(v[0] + v[1] for _, v in items)
        for cidx, chunk in enumerate(chunks):
            posting_rows.append(
                {
                    "term": term,
                    "document_indices": [d for d, _ in chunk],
                    "title_frequencies": [v[0] for _, v in chunk],
                    "body_frequencies": [v[1] for _, v in chunk],
                    "document_lengths": [int(round(doc_len[d])) for d, _ in chunk],
                    "document_frequency": int(dfreq),
                    "corpus_frequency": int(cfreq),
                    "idf": float(idf[term]),
                    "posting_chunk_index": int(cidx),
                    "posting_chunk_count": int(n_chunks),
                    "schema_version": SCHEMA_VERSION,
                }
            )
    postings_df = pd.DataFrame(posting_rows)

    stats = {
        "k1": K1,
        "b": B,
        "title_weight": TITLE_WEIGHT,
        "body_weight": BODY_WEIGHT,
        "average_document_length": avgdl,
        "tokenizer": "fts5-unicode61-remove-diacritics-2-python/v1",
        "max_query_terms": MAX_QUERY_TERMS,
        "posting_rows_per_record": POSTING_ROWS_PER_RECORD,
        "terms_per_shard": TERMS_PER_SHARD,
        "n_docs": n,
        "n_terms": len(terms),
        "n_posting_rows": int(len(postings_df)),
        "n_postings": int(sum(len(postings[t]) for t in terms)),
    }
    return {
        "documents": documents,
        "postings": postings_df,
        "postings_map": postings,
        "idf": idf,
        "doc_len": doc_len,
        "avgdl": avgdl,
        "title_toks": title_toks,
        "body_toks": body_toks,
        "stats": stats,
    }


def _tf_score(tf: float, dl: float, avgdl: float) -> float:
    denom = tf + K1 * (1.0 - B + B * (dl / avgdl if avgdl else 0.0))
    if denom == 0:
        return 0.0
    return (tf * (K1 + 1.0)) / denom


def score_query(
    query: str,
    index: dict[str, Any],
    top_k: int = 10,
) -> list[tuple[int, float]]:
    q_terms = tokenize(query)[:MAX_QUERY_TERMS]
    if not q_terms:
        return []
    postings = index["postings_map"]
    idf = index["idf"]
    doc_len = index["doc_len"]
    avgdl = index["avgdl"] or 1.0
    scores: dict[int, float] = defaultdict(float)
    for term in q_terms:
        plist = postings.get(term)
        if not plist:
            continue
        w = idf.get(term, 0.0)
        for doc, (ttf, btf) in plist.items():
            tf = TITLE_WEIGHT * ttf + BODY_WEIGHT * btf
            scores[doc] += w * _tf_score(tf, float(doc_len[doc]), avgdl)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:top_k]


def bm25_neighbors(index: dict[str, Any], k: int = 8) -> list[list[tuple[int, float]]]:
    """Top-k BM25 neighbors from title tokens (body prefix only if title is empty)."""
    import heapq

    n = index["stats"]["n_docs"]
    postings = index["postings_map"]
    idf = index["idf"]
    doc_len = index["doc_len"]
    avgdl = index["avgdl"] or 1.0
    title_toks = index["title_toks"]
    body_toks = index["body_toks"]
    df_cap = max(256, min(1500, n // 40 or 1))
    # Precompute posting arrays so the inner loop is not dict-item unpacking.
    term_docs: dict[str, np.ndarray] = {}
    term_pay: dict[str, np.ndarray] = {}
    for term, plist in postings.items():
        if len(plist) > df_cap:
            continue
        docs = np.fromiter(plist.keys(), dtype=np.int32, count=len(plist))
        tfs = np.empty(len(plist), dtype=np.float64)
        for j, (doc, (ttf, btf)) in enumerate(plist.items()):
            tf = TITLE_WEIGHT * ttf + BODY_WEIGHT * btf
            tfs[j] = _tf_score(tf, float(doc_len[doc]), avgdl)
        term_docs[term] = docs
        term_pay[term] = tfs * float(idf.get(term, 0.0))

    neighbors: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    step = 20000 if n >= 40000 else max(n, 1)
    for i in range(n):
        if i and i % step == 0:
            print(f"bm25 neighbors {i}/{n}", flush=True)
        q_terms = title_toks[i][:16] or body_toks[i][:16]
        if not q_terms:
            continue
        tf_q: dict[str, int] = defaultdict(int)
        for tok in q_terms:
            tf_q[tok] += 1
        scores: dict[int, float] = defaultdict(float)
        for term, qtf in tf_q.items():
            docs = term_docs.get(term)
            if docs is None:
                continue
            pay = term_pay[term] * qtf
            for doc, val in zip(docs, pay):
                di = int(doc)
                if di != i:
                    scores[di] += float(val)
        if scores:
            neighbors[i] = heapq.nlargest(k, scores.items(), key=lambda kv: kv[1])
    print(f"bm25 neighbors {n}/{n}", flush=True)
    return neighbors
