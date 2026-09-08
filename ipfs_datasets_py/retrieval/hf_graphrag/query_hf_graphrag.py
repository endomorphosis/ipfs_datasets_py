#!/usr/bin/env python3
"""Standalone thin-client search for a Hugging Face GraphRAG release.

Hub consumers can copy ``scripts/query_hf_graphrag.py`` (and
``semantic_traversal.py`` when present) out of the dataset and search without
downloading the full corpus:

  python scripts/query_hf_graphrag.py --local-root . bm25 "foia agency"
  python scripts/query_hf_graphrag.py --repo-id ORG/NAME --revision PIN \\
      neighbors bafkrei... --direction both --limit 25

Requires pyarrow. Remote queries also need huggingface_hub. Vector search
needs numpy; local embedding needs sentence-transformers.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_./:][a-z0-9]+)*", re.I)
DEFAULT_MANIFEST = "manifest.json"
DEFAULT_CACHE = Path("~/.cache/ipfs_datasets_py/hf-graphrag-query").expanduser()


class RemoteQueryError(RuntimeError):
    """Malformed release or missing dependency."""


def _safe_relative(path: str) -> PurePosixPath:
    rel = PurePosixPath(str(path or "").replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RemoteQueryError(f"unsafe release path: {path!r}")
    return rel


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactResolver:
    """Fetch only requested files from a local root or the Hub."""

    def __init__(
        self,
        *,
        repo_id: str,
        revision: str,
        token: str | None,
        cache_dir: Path,
        local_root: Path | None,
    ) -> None:
        self.repo_id = repo_id
        self.revision = revision
        self.token = token
        self.cache_dir = cache_dir
        self.local_root = local_root.expanduser().resolve() if local_root else None
        self.fetched: dict[str, int] = {}

    def path(self, relative: str, descriptor: Mapping[str, Any] | None = None) -> Path:
        safe = _safe_relative(relative)
        if self.local_root is not None:
            path = (self.local_root.joinpath(*safe.parts)).resolve()
            try:
                path.relative_to(self.local_root)
            except ValueError as exc:
                raise RemoteQueryError("path escapes release root") from exc
            if not path.is_file():
                raise RemoteQueryError(f"missing {relative}")
        else:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RemoteQueryError("huggingface_hub is required for --repo-id") from exc
            path = Path(
                hf_hub_download(
                    repo_id=self.repo_id,
                    filename=safe.as_posix(),
                    repo_type="dataset",
                    revision=self.revision,
                    token=self.token,
                    cache_dir=str(self.cache_dir),
                )
            )
        if descriptor and descriptor.get("sha256"):
            got = _sha256(path)
            expected = str(descriptor["sha256"]).removeprefix("sha256:")
            if got != expected:
                raise RemoteQueryError(f"sha256 mismatch for {relative}")
        self.fetched[safe.as_posix()] = path.stat().st_size
        return path

    def json(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def parquet(self, relative: str, columns: Sequence[str] | None = None, descriptor=None):
        import pyarrow.parquet as pq

        return pq.read_table(
            self.path(relative, descriptor),
            columns=list(columns) if columns else None,
        )

    def trace(self) -> dict[str, Any]:
        files = [
            {"relative_path": path, "size_bytes": size}
            for path, size in sorted(self.fetched.items())
        ]
        return {
            "file_count": len(files),
            "files": files,
            "total_file_bytes": sum(item["size_bytes"] for item in files),
        }


def _tokenize(query: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(query or "")]


def _bm25_score(tf: float, idf: float, doc_len: float, avgdl: float, k1: float, b: float) -> float:
    if tf <= 0 or idf <= 0 or avgdl <= 0:
        return 0.0
    denom = tf + k1 * (1.0 - b + b * (doc_len / avgdl))
    if denom <= 0:
        return 0.0
    return idf * (tf * (k1 + 1.0) / denom)


def _index_rows(manifest: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    indexes = manifest.get("indexes") or {}
    row = indexes.get(key) or indexes.get(key.replace("_", "-"))
    return [row] if isinstance(row, dict) and row.get("relative_path") else []


class ThinClient:
    def __init__(self, resolver: ArtifactResolver, manifest: Mapping[str, Any]) -> None:
        self.resolver = resolver
        self.manifest = dict(manifest)

    def _locator(self, name: str) -> list[dict[str, Any]]:
        indexes = self.manifest.get("indexes") or {}
        aliases = {
            "bm25_keyword_shards": (
                "bm25_keyword_shards",
                "bm25_postings",
                "bm25_keyword_index",
            ),
            "bm25_postings": (
                "bm25_postings",
                "bm25_keyword_shards",
                "bm25_keyword_index",
            ),
        }.get(name, (name,))
        candidates: list[tuple[str, Mapping[str, Any] | None]] = []
        seen: set[str] = set()
        for key in aliases:
            desc = indexes.get(key)
            if isinstance(desc, dict) and desc.get("relative_path"):
                relative = str(desc["relative_path"])
                if relative not in seen:
                    candidates.append((relative, desc))
                    seen.add(relative)
            for fallback in (f"indexes/{key}.parquet", f"indexes/{key}.json"):
                if fallback not in seen:
                    candidates.append((fallback, None))
                    seen.add(fallback)
        for relative, desc in candidates:
            try:
                if relative.endswith(".json"):
                    payload = self.resolver.json(relative)
                    rows = payload.get("routing") or payload.get("shards") or payload
                    if isinstance(rows, list):
                        return [dict(row) for row in rows]
                    continue
                try:
                    table = self.resolver.parquet(relative, descriptor=desc)
                except RemoteQueryError as exc:
                    # Rewritten locators often keep the country-pack name
                    # with a stale sha256. Retry the same path unchecked.
                    if "sha256 mismatch" not in str(exc) or desc is None:
                        raise
                    table = self.resolver.parquet(relative, descriptor=None)
                return table.to_pylist()
            except (RemoteQueryError, OSError, FileNotFoundError):
                continue
        raise RemoteQueryError(f"locator missing: {name}")

    def _covering(self, rows: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
        hits = []
        for row in rows:
            first = str(row.get("first_key") or "")
            last = str(row.get("last_key") or "")
            if first <= key <= last:
                hits.append(dict(row))
        return hits or [dict(row) for row in rows if str(row.get("first_key") or "") == key]

    def bm25(self, query: str, *, top_k: int) -> dict[str, Any]:
        terms = _tokenize(query)[:64]
        config = dict(self.manifest.get("bm25") or {})
        k1 = float(config.get("k1") or 1.2)
        b = float(config.get("b") or 0.75)
        avgdl = float(config.get("average_document_length") or config.get("avg_doc_tokens") or 1.0)
        title_w = float(config.get("title_weight") or 1.0)
        body_w = float(config.get("body_weight") or 1.0)
        loc = self._locator("bm25_keyword_shards") or self._locator("bm25_postings")
        scores: dict[str, float] = defaultdict(float)
        matched: dict[str, set[str]] = defaultdict(set)
        shards = 0
        for term in terms:
            for row in self._covering(loc, term):
                relative = str(row.get("relative_path") or "")
                table = self.resolver.parquet(relative, descriptor=row)
                names = set(table.schema.names)
                shards += 1
                if "document_indices" in names:
                    for rec in table.to_pylist():
                        if str(rec.get("term")) != term:
                            continue
                        idf = float(rec.get("idf") or 0.0)
                        for doc, title_tf, body_tf, length in zip(
                            rec.get("document_indices") or (),
                            rec.get("title_frequencies") or (),
                            rec.get("body_frequencies") or (),
                            rec.get("document_lengths") or (),
                        ):
                            tf = title_w * float(title_tf or 0) + body_w * float(body_tf or 0)
                            key = str(int(doc))
                            scores[key] += _bm25_score(tf, idf, float(length or 0), avgdl, k1, b)
                            matched[key].add(term)
                elif "legal_id" in names:
                    for rec in table.to_pylist():
                        if str(rec.get("term")) != term:
                            continue
                        key = str(rec.get("legal_id") or rec.get("entry_cid"))
                        scores[key] += float(rec.get("tf") or 0)
                        matched[key].add(term)
        ranked = heapq.nlargest(top_k, scores.items(), key=lambda item: item[1])
        hits = [
            {
                "id": doc,
                "score": score,
                "matched_terms": sorted(matched[doc]),
                "authority": "context_only",
            }
            for doc, score in ranked
        ]
        return {"mode": "bm25", "query": query, "hits": hits, "fetch_trace": self.resolver.trace(), "shards": shards}

    def neighbors(self, node_cid: str, *, direction: str, limit: int) -> dict[str, Any]:
        name = (
            "graph_outgoing_adjacency"
            if direction in {"out", "outgoing"}
            else "graph_incoming_adjacency"
        )
        if direction in {"both"}:
            left = self.neighbors(node_cid, direction="outgoing", limit=limit)
            right = self.neighbors(node_cid, direction="incoming", limit=limit)
            return {
                "mode": "neighbors",
                "node_cid": node_cid,
                "outgoing": left.get("hits"),
                "incoming": right.get("hits"),
                "fetch_trace": self.resolver.trace(),
            }
        loc = self._locator(name)
        pages = []
        for row in self._covering(loc, node_cid):
            table = self.resolver.parquet(str(row["relative_path"]), descriptor=row)
            for rec in table.to_pylist():
                if str(rec.get("node_cid")) != node_cid:
                    continue
                pages.append(rec)
        hits = []
        for rec in pages:
            neighbors = rec.get("neighbor_cids") or []
            types = rec.get("edge_types") or []
            methods = rec.get("retrieval_methods") or []
            scores = rec.get("scores") or []
            for i, neighbor in enumerate(neighbors[:limit]):
                hits.append(
                    {
                        "neighbor_cid": neighbor,
                        "edge_type": types[i] if i < len(types) else "",
                        "retrieval_method": methods[i] if i < len(methods) else "",
                        "score": scores[i] if i < len(scores) else None,
                    }
                )
            if len(hits) >= limit:
                break
        return {
            "mode": "neighbors",
            "node_cid": node_cid,
            "direction": direction,
            "hits": hits[:limit],
            "fetch_trace": self.resolver.trace(),
        }

    def walk(self, node_cid: str, *, max_depth: int, max_nodes: int, direction: str) -> dict[str, Any]:
        seen = {node_cid}
        frontier = [node_cid]
        edges = []
        depth = 0
        while frontier and depth < max_depth and len(seen) < max_nodes:
            nxt = []
            for node in frontier:
                page = self.neighbors(node, direction=direction if direction != "both" else "outgoing", limit=32)
                for hit in page.get("hits") or []:
                    dst = str(hit.get("neighbor_cid") or "")
                    if not dst or dst in seen:
                        continue
                    seen.add(dst)
                    edges.append({"src": node, **hit})
                    nxt.append(dst)
                    if len(seen) >= max_nodes:
                        break
            frontier = nxt
            depth += 1
        return {
            "mode": "walk",
            "seed": node_cid,
            "nodes": sorted(seen),
            "edges": edges,
            "depth": depth,
            "fetch_trace": self.resolver.trace(),
        }


def _load_query_vector(text: str, model_name: str) -> list[float]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    vector = model.encode([text], normalize_embeddings=True)[0]
    return [float(value) for value in vector]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default="")
    parser.add_argument("--revision", default="")
    parser.add_argument("--local-root", default="")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    bm25 = sub.add_parser("bm25")
    bm25.add_argument("query")
    bm25.add_argument("--top-k", type=int, default=10)
    vec = sub.add_parser("vector")
    vec.add_argument("query")
    vec.add_argument("--top-k", type=int, default=10)
    vec.add_argument("--model", default="")
    neigh = sub.add_parser("neighbors")
    neigh.add_argument("node_cid")
    neigh.add_argument("--direction", default="both")
    neigh.add_argument("--limit", type=int, default=25)
    walk = sub.add_parser("walk")
    walk.add_argument("node_cid")
    walk.add_argument("--direction", default="outgoing")
    walk.add_argument("--max-depth", type=int, default=2)
    walk.add_argument("--max-nodes", type=int, default=100)
    args = parser.parse_args(argv)
    local = Path(args.local_root).expanduser() if args.local_root else None
    if local is None and not args.repo_id:
        raise SystemExit("pass --local-root or --repo-id")
    if args.repo_id and not args.revision:
        raise SystemExit("remote queries require an immutable --revision pin")
    resolver = ArtifactResolver(
        repo_id=args.repo_id,
        revision=args.revision,
        token=os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        cache_dir=Path(args.cache_dir),
        local_root=local,
    )
    manifest = resolver.json(args.manifest)
    client = ThinClient(resolver, manifest)
    if args.mode == "bm25":
        result = client.bm25(args.query, top_k=max(1, args.top_k))
    elif args.mode == "neighbors":
        result = client.neighbors(args.node_cid, direction=args.direction, limit=max(1, args.limit))
    elif args.mode == "walk":
        result = client.walk(
            args.node_cid,
            max_depth=max(1, args.max_depth),
            max_nodes=max(1, args.max_nodes),
            direction=args.direction,
        )
    else:
        raise SystemExit("vector search in the standalone client needs --model; use neighbors/bm25 here")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
