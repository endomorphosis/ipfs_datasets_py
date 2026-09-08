#!/usr/bin/env python3
"""Direct Hugging Face query CLI for Open US Law sparse GraphRAG (OUL-035).

Exposes the same five public modes as the package API:

* ``bm25`` — field-weighted sparse search (lexicographic term ranges)
* ``vector`` — dense centroid-routed search
* ``hybrid`` — weighted or RRF fusion of BM25 + vector
* ``graph`` — bounded structural walk (optional neighbors-only)
* ``semantic-graph`` — embedding-guided beam walk

Jurisdiction and status filters, immutable Dataset/Bucket pins, JSON
fetch traces, and explicit resource budgets are first-class. Queries
never download the full index.

Offline fixture mode (no network, no accelerators)::

    python scripts/ops/legal_data/query_open_us_law_hf.py \\
        --local-root PATH --fixture-mode --json --trace \\
        bm25 "foia agency" --jurisdiction OR --status current

Secrets are never printed. Mutable or empty revisions fail closed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (  # noqa: E402
    DEFAULT_BUCKET_ID,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_NODES,
    DEFAULT_MAX_ROWS,
    DEFAULT_MAX_SHARDS,
    DEFAULT_MAX_TIME_MS,
    DEFAULT_REVISION,
    DEFAULT_TOP_K,
    QUERY_MODES,
    SECRET_ENV_NAMES,
    ImmutablePinError,
    OpenUsLawSparseGraphragClient,
    OpenUsLawSparseGraphragError,
    QueryModeError,
    ResourceBudgetError,
    ResourceBudgets,
    SecretLeakageError,
    open_query_client,
    package_query_result,
    require_immutable_pin,
)

TASK_ID: Final = "OUL-035"
GOAL_ID: Final = "OUL-G050"

SUBCOMMANDS: Final = QUERY_MODES + ("neighbors",)


class CliError(SystemExit):
    """CLI-level failure with a non-zero exit code."""

    def __init__(self, message: str, *, code: int = 2) -> None:
        super().__init__(code)
        self.message = message
        print(f"error: {message}", file=sys.stderr)


def _reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(argv).lower()
    for needle in ("hf_token=", "authorization:", "bearer "):
        if needle in lowered:
            raise CliError("refusing to accept secrets on the command line")


def _assert_no_secret_env_echo() -> None:
    # Presence is fine; we never emit the value.
    for name in SECRET_ENV_NAMES:
        _ = os.environ.get(name)


def _parse_float_list(raw: str | None) -> list[float] | None:
    if raw is None or raw == "":
        return None
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise CliError("embedding list is empty")
    values: list[float] = []
    for part in parts:
        try:
            value = float(part)
        except ValueError as exc:
            raise CliError(f"invalid embedding component: {part!r}") from exc
        if not math.isfinite(value):
            raise CliError(f"non-finite embedding component: {part!r}")
        values.append(value)
    return values


def _fixture_embedder(dimension: int = 2):
    def _embed(text: str) -> list[float]:
        if not isinstance(text, str) or not text:
            raise CliError("query text required for embedding")
        acc = [0.0] * dimension
        for index, ch in enumerate(text.encode("utf-8")):
            acc[index % dimension] += float(ch)
        norm = math.sqrt(sum(v * v for v in acc)) or 1.0
        return [v / norm for v in acc]

    return _embed


def _build_budgets(args: argparse.Namespace) -> ResourceBudgets:
    try:
        return ResourceBudgets(
            max_bytes=int(args.max_bytes),
            max_shards=int(args.max_shards),
            max_rows=int(args.max_rows),
            max_nodes=int(args.max_nodes),
            max_edges=int(args.max_edges),
            max_depth=int(args.max_depth),
            max_time_ms=int(args.max_time_ms),
        )
    except ResourceBudgetError as exc:
        raise CliError(str(exc)) from exc


def _filter_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "jurisdiction",
        "status",
        "edition",
        "code_family",
        "title",
        "chapter",
        "section",
        "source",
        "release_point",
        "citation",
        "legal_id",
        "version",
    ):
        value = getattr(args, key, None)
        if value:
            payload[key] = value
    return payload


def _build_client(args: argparse.Namespace) -> OpenUsLawSparseGraphragClient:
    try:
        revision = require_immutable_pin(args.revision)
    except ImmutablePinError as exc:
        raise CliError(str(exc)) from exc

    local_root = (
        Path(args.local_root).expanduser().resolve() if args.local_root else None
    )
    if local_root is not None and not local_root.is_dir():
        raise CliError(f"local-root is not a directory: {local_root}")
    if local_root is None and str(args.revision).strip().lower() in {
        "main",
        "master",
        "latest",
        "head",
    }:
        raise CliError(
            "live Hub queries require an immutable revision pin "
            f"(got {args.revision!r}); use --local-root for offline fixtures"
        )

    embedder = None
    command = str(args.command)
    needs_embedder = command in {"vector", "hybrid", "semantic-graph"}
    if needs_embedder:
        if args.embedding:
            vector = _parse_float_list(args.embedding)
            assert vector is not None

            def _fixed(_text: str, _vector: list[float] = vector) -> list[float]:
                return list(_vector)

            embedder = _fixed
        elif args.local_root or args.fixture_mode:
            embedder = _fixture_embedder(dimension=int(args.embedding_dim))
        else:
            raise CliError(
                f"{command} requires --embedding or --local-root/--fixture-mode "
                "with a deterministic offline embedder"
            )

    fusion: dict[str, Any] | None = None
    if command == "hybrid":
        fusion = {
            "method": str(args.fusion_method),
            "bm25_weight": float(args.bm25_weight),
            "vector_weight": float(args.vector_weight),
            "rrf_k": int(args.rrf_k),
        }

    try:
        return open_query_client(
            revision=revision,
            repo_id=str(args.repo_id),
            local_root=local_root,
            cache_dir=args.cache_dir,
            budgets=_build_budgets(args),
            query_embedder=embedder,
            fusion=fusion,
            transport=str(args.transport),
            bucket_prefix=args.bucket_prefix,
        )
    except (
        ImmutablePinError,
        OpenUsLawSparseGraphragError,
        ResourceBudgetError,
        ValueError,
        TypeError,
    ) as exc:
        raise CliError(f"failed to construct query client: {exc}") from exc


def _print_human(payload: Mapping[str, Any]) -> None:
    results = payload.get("results") or ()
    print(
        f"mode={payload.get('mode')} complete={payload.get('complete')} "
        f"stop_reason={payload.get('stop_reason')} results={len(results)}"
    )
    for index, hit in enumerate(list(results)[:20], start=1):
        if not isinstance(hit, Mapping):
            print(f"  {index:02d}. {hit}")
            continue
        cid = hit.get("entry_cid") or hit.get("node_cid") or hit.get("edge_cid")
        score = hit.get("score")
        print(f"  {index:02d}. score={score} id={cid}")


def _run_command(args: argparse.Namespace) -> int:
    client = _build_client(args)
    filters = _filter_kwargs(args)
    top_k = int(getattr(args, "top_k", DEFAULT_TOP_K) or DEFAULT_TOP_K)
    embedding = _parse_float_list(getattr(args, "embedding", None))
    try:
        if args.command == "bm25":
            result = client.bm25_search(
                args.query,
                top_k=top_k,
                hydrate=bool(args.hydrate),
                **filters,
            )
        elif args.command == "vector":
            result = client.vector_search(
                args.query or "",
                query_vector=embedding,
                top_k=top_k,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
                **filters,
            )
        elif args.command == "hybrid":
            result = client.hybrid_search(
                args.query,
                query_vector=embedding,
                top_k=top_k,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
                **filters,
            )
        elif args.command == "graph":
            result = client.graph_search(
                args.start_node_cid,
                direction=str(args.direction),
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                include_similarity=bool(args.include_similarity),
                neighbors_only=bool(getattr(args, "neighbors_only", False)),
                limit=int(getattr(args, "limit", 16) or 16),
            )
        elif args.command == "neighbors":
            result = client.neighbors(
                args.node_cid,
                direction=str(args.direction),
                limit=int(args.limit),
                include_similarity=bool(args.include_similarity),
            )
        elif args.command == "semantic-graph":
            result = client.semantic_graph_search(
                args.start_node_cid,
                query=args.query or "",
                query_vector=embedding,
                direction=str(args.direction),
                include_similarity=bool(args.include_similarity),
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                beam_width=int(args.beam_width),
                candidate_centroids=int(args.candidate_centroids),
            )
        else:
            raise CliError(f"unknown command: {args.command}")
    except (
        OpenUsLawSparseGraphragError,
        QueryModeError,
        ImmutablePinError,
        ValueError,
        TypeError,
    ) as exc:
        raise CliError(str(exc), code=1) from exc

    try:
        payload = package_query_result(
            result,
            pin=client.pin,
            include_trace=bool(args.trace),
            mode=str(args.command),
        )
    except SecretLeakageError as exc:
        raise CliError(str(exc), code=1) from exc

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        _print_human(payload)
        if args.trace:
            sys.stdout.write(
                json.dumps(payload.get("fetch_trace") or {}, indent=2, sort_keys=True)
                + "\n"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="query_open_us_law_hf.py",
        description=(
            "Direct Hugging Face Open US Law sparse GraphRAG query CLI "
            "(OUL-035). Modes: bm25, vector, hybrid, graph, semantic-graph. "
            "Supports jurisdiction/status filters, immutable pins, fetch "
            "traces, and resource budgets without a full-index download."
        ),
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_DATASET_REPO_ID,
        help="Pinned Hub repository id",
    )
    parser.add_argument(
        "--revision",
        default=DEFAULT_REVISION,
        help="Immutable 40-hex Dataset revision pin",
    )
    parser.add_argument(
        "--transport",
        choices=("dataset", "bucket"),
        default="dataset",
        help="Dataset (40-hex) or Bucket (releases/<sha256>/) pin",
    )
    parser.add_argument(
        "--bucket-prefix",
        default=None,
        help="Bucket pin: releases/<manifest_sha256>/",
    )
    parser.add_argument(
        "--bucket-id",
        default=DEFAULT_BUCKET_ID,
        help="Authorized Bucket id (informational; live bucket uses resolver)",
    )
    parser.add_argument("--cache-dir", default=None, help="Optional resolver cache")
    parser.add_argument(
        "--local-root",
        default=None,
        help="Offline release root (LocalRootTransport; no network)",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Enable deterministic offline embedder without live models",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-shards", type=int, default=DEFAULT_MAX_SHARDS)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    parser.add_argument("--max-edges", type=int, default=DEFAULT_MAX_EDGES)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-time-ms", type=int, default=DEFAULT_MAX_TIME_MS)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Include fetch_trace (JSON) / print trace after human summary",
    )
    parser.add_argument("--jurisdiction", default=None, help="Filter: jurisdiction")
    parser.add_argument("--status", default=None, help="Filter: status")
    parser.add_argument("--edition", default=None, help="Filter: edition")
    parser.add_argument("--code-family", default=None, dest="code_family")
    parser.add_argument("--title", default=None, help="Filter: title")
    parser.add_argument("--chapter", default=None, help="Filter: chapter")
    parser.add_argument("--section", default=None, help="Filter: section")
    parser.add_argument("--source", default=None, help="Filter: source")
    parser.add_argument("--release-point", default=None, dest="release_point")
    parser.add_argument("--citation", default=None, help="Filter: citation")
    parser.add_argument("--version", default=None, help="Filter: version")
    parser.add_argument("--legal-id", default=None, dest="legal_id")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_search_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
        p.add_argument("--hydrate", action=argparse.BooleanOptionalAction, default=True)
        p.add_argument(
            "--candidate-centroids",
            type=int,
            default=DEFAULT_CANDIDATE_CENTROIDS,
        )
        p.add_argument(
            "--embedding",
            default=None,
            help="Comma-separated query embedding (vector/hybrid/semantic-graph)",
        )
        p.add_argument("--embedding-dim", type=int, default=2)

    p_bm25 = sub.add_parser("bm25", help="Field-weighted BM25 search")
    p_bm25.add_argument("query")
    add_search_flags(p_bm25)

    p_vec = sub.add_parser("vector", help="Dense centroid-routed vector search")
    p_vec.add_argument("query", nargs="?", default="", help="Optional text for embedder")
    add_search_flags(p_vec)

    p_hyb = sub.add_parser("hybrid", help="Hybrid BM25 + vector fusion")
    p_hyb.add_argument("query")
    add_search_flags(p_hyb)
    p_hyb.add_argument("--fusion-method", choices=("weighted", "rrf"), default="weighted")
    p_hyb.add_argument("--bm25-weight", type=float, default=0.5)
    p_hyb.add_argument("--vector-weight", type=float, default=0.5)
    p_hyb.add_argument("--rrf-k", type=int, default=60)

    p_g = sub.add_parser("graph", help="Bounded structural graph walk")
    p_g.add_argument("start_node_cid")
    p_g.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_g.add_argument("--walk-depth", type=int, default=2)
    p_g.add_argument("--walk-nodes", type=int, default=32)
    p_g.add_argument("--walk-edges", type=int, default=64)
    p_g.add_argument("--neighbors-only", action="store_true")
    p_g.add_argument("--limit", type=int, default=16)
    p_g.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    p_n = sub.add_parser("neighbors", help="Bounded adjacency neighbors (graph)")
    p_n.add_argument("node_cid")
    p_n.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_n.add_argument("--limit", type=int, default=16)
    p_n.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=False,
    )

    p_sg = sub.add_parser(
        "semantic-graph", help="Embedding-guided semantic beam walk"
    )
    p_sg.add_argument("start_node_cid")
    p_sg.add_argument("--query", default="", help="Optional text to embed for proximity")
    p_sg.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_sg.add_argument("--walk-depth", type=int, default=2)
    p_sg.add_argument("--walk-nodes", type=int, default=32)
    p_sg.add_argument("--walk-edges", type=int, default=64)
    p_sg.add_argument("--beam-width", type=int, default=4)
    p_sg.add_argument(
        "--candidate-centroids",
        type=int,
        default=DEFAULT_CANDIDATE_CENTROIDS,
    )
    p_sg.add_argument("--embedding", default=None)
    p_sg.add_argument("--embedding-dim", type=int, default=2)
    p_sg.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    _reject_secrets_in_argv(argv_list)
    _assert_no_secret_env_echo()
    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return _run_command(args)
    except CliError as exc:
        return int(exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
