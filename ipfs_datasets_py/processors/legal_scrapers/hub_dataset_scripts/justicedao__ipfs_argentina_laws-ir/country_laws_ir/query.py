#!/usr/bin/env python3
"""Thin-client query for country-laws IR releases (local dir or Hub)."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

K1 = 1.2
B = 0.75
TITLE_WEIGHT = 5.0
BODY_WEIGHT = 1.0
MAX_QUERY_TERMS = 64


def tokenize(text: str) -> list[str]:
    import re
    import unicodedata

    if not text:
        return []
    nfkd = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()
    return re.findall(r"[0-9A-Za-z]+", folded)


class Release:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def _read(self, rel: str) -> pd.DataFrame:
        path = self.root / rel
        if path.is_dir():
            files = sorted(path.glob("*.parquet"))
            return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()
        return pd.read_parquet(path)

    def bm25(self, query: str, top_k: int = 10) -> list[dict]:
        q_terms = tokenize(query)[:MAX_QUERY_TERMS]
        if not q_terms:
            return []
        shards = pd.read_parquet(self.root / "indexes" / "bm25_keyword_shards.parquet")
        needed = set()
        for term in q_terms:
            hit = shards[(shards["first_key"] <= term) & (shards["last_key"] >= term)]
            if hit.empty:
                # fallback scan nearby shards
                hit = shards
            for rel in hit["relative_path"].tolist():
                needed.add(rel)
        postings = pd.concat(
            [pd.read_parquet(self.root / rel) for rel in sorted(needed)],
            ignore_index=True,
        )
        postings = postings[postings["term"].isin(q_terms)]
        docs = self._read("data/bm25/documents")
        avgdl = float(self.manifest["bm25"]["average_document_length"]) or 1.0
        scores: dict[int, float] = defaultdict(float)
        for rec in postings.itertuples(index=False):
            idf = float(rec.idf)
            for di, ttf, btf, dl in zip(rec.document_indices, rec.title_frequencies, rec.body_frequencies, rec.document_lengths):
                tf = TITLE_WEIGHT * int(ttf) + BODY_WEIGHT * int(btf)
                denom = tf + K1 * (1.0 - B + B * (int(dl) / avgdl))
                if denom:
                    scores[int(di)] += idf * (tf * (K1 + 1.0)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        by_idx = docs.set_index("document_index")
        out = []
        for di, score in ranked:
            row = by_idx.loc[di]
            out.append(
                {
                    "document_index": int(di),
                    "entry_cid": row["entry_cid"],
                    "title": row["title"],
                    "record_type": row["record_type"],
                    "law_id": row["law_id"],
                    "score": float(score),
                }
            )
        return out

    def vector(self, query: str, top_k: int = 10, candidate_centroids: int = 4, device: str = "cpu") -> list[dict]:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self.manifest["vector"]["model_name"], device=device)
        q = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)
        meta = pd.read_parquet(self.root / "indexes" / "vector_chunks.parquet")
        cents = np.stack(meta["centroid"].map(lambda c: np.asarray(c, dtype=np.float32)).to_numpy())
        sims = cents @ q
        order = np.argsort(-sims)[: max(1, candidate_centroids)]
        shards = meta.iloc[order]
        frames = [pd.read_parquet(self.root / rel) for rel in shards["relative_path"].tolist()]
        vecs = pd.concat(frames, ignore_index=True)
        emb = np.stack(vecs["embedding"].map(lambda e: np.asarray(e, dtype=np.float32)).to_numpy())
        scores = emb @ q
        top = np.argsort(-scores)[:top_k]
        out = []
        for i in top:
            row = vecs.iloc[int(i)]
            out.append(
                {
                    "document_index": int(row["document_index"]),
                    "entry_cid": row["entry_cid"],
                    "title": row["title"],
                    "record_type": row["record_type"],
                    "law_id": row["law_id"],
                    "score": float(scores[int(i)]),
                }
            )
        return out

    def neighbors(self, node_cid: str, direction: str = "both", limit: int = 25) -> list[dict]:
        dirs = ["incoming", "outgoing"] if direction == "both" else [direction]
        hits = []
        for d in dirs:
            path = self.root / "data" / "graph" / "adjacency" / d
            files = sorted(path.glob("*.parquet"))
            for f in files:
                df = pd.read_parquet(f)
                sub = df[df["node_cid"] == node_cid]
                for rec in sub.itertuples(index=False):
                    for i, neigh in enumerate(rec.neighbor_cids):
                        hits.append(
                            {
                                "direction": d,
                                "node_cid": node_cid,
                                "neighbor_cid": neigh,
                                "edge_type": rec.edge_types[i] if i < len(rec.edge_types) else "",
                                "score": rec.scores[i] if rec.scores is not None and i < len(rec.scores) else None,
                            }
                        )
        hits.sort(key=lambda r: (-(r["score"] or 0), r["neighbor_cid"]))
        return hits[:limit]


def _print(rows: list[dict]) -> None:
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def _resolve_root(args: argparse.Namespace) -> Path:
    if args.local_dir:
        return Path(args.local_dir)
    if args.repo_id:
        from huggingface_hub import snapshot_download

        from .auth import configure_hf, load_token

        configure_hf()
        kwargs = {"repo_id": args.repo_id, "repo_type": "dataset", "token": load_token()}
        if args.revision:
            kwargs["revision"] = args.revision
        return Path(snapshot_download(**kwargs))
    raise SystemExit("pass --local-dir or --repo-id")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Query a country-laws IR release")
    p.add_argument("--local-dir")
    p.add_argument("--repo-id")
    p.add_argument("--revision", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bm25")
    b.add_argument("query")
    b.add_argument("--top-k", type=int, default=10)

    v = sub.add_parser("vector")
    v.add_argument("query")
    v.add_argument("--top-k", type=int, default=10)
    v.add_argument("--candidate-centroids", type=int, default=4)
    v.add_argument("--device", default="cpu")

    g = sub.add_parser("graph")
    g.add_argument("action", choices=["neighbors"])
    g.add_argument("node_cid")
    g.add_argument("--direction", default="both")
    g.add_argument("--limit", type=int, default=25)

    args = p.parse_args(argv)
    rel = Release(_resolve_root(args))
    if args.cmd == "bm25":
        _print(rel.bm25(args.query, top_k=args.top_k))
    elif args.cmd == "vector":
        _print(rel.vector(args.query, top_k=args.top_k, candidate_centroids=args.candidate_centroids, device=args.device))
    elif args.cmd == "graph":
        _print(rel.neighbors(args.node_cid, direction=args.direction, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
