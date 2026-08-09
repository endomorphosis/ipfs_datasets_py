#!/usr/bin/env python3
"""Direct Hugging Face query CLI for US Code sparse GraphRAG (USCIR-028).

Exposes six subcommands that map 1:1 onto :class:`UscodeQueryClient`:

* ``bm25`` — field-weighted sparse search
* ``vector`` — dense centroid-routed search
* ``hybrid`` — weighted or RRF fusion of BM25 + vector
* ``neighbors`` — bounded adjacency neighbors
* ``graph-walk`` — structural BFS walk
* ``semantic-graph-walk`` — embedding-guided beam walk

Offline fixture mode (no network, no accelerators)::

    python scripts/ops/legal_data/query_uscode_hf.py --local-root PATH bm25 "foia"

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

from ipfs_datasets_py.processors.legal_data.uscode_query import (  # noqa: E402
    FusionConfig,
    LegalFilters,
    SemanticBeamConfig,
    UscodeQueryClient,
    UscodeQueryError,
    UscodeQueryInputError,
    UscodeQueryResult,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits  # noqa: E402
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    ImmutableHubResolver,
    LocalRootTransport,
    MutableRevisionError,
    ResolverError,
)

TASK_ID: Final = "USCIR-028"
GOAL_ID: Final = "USCIR-G070"
DEFAULT_REPO: Final = "justicedao/ipfs_uscode"
# Immutable-looking default; operators must pin explicitly for live Hub use.
DEFAULT_REVISION: Final = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)

SUBCOMMANDS: Final = (
    "bm25",
    "vector",
    "hybrid",
    "neighbors",
    "graph-walk",
    "semantic-graph-walk",
)


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
    # Defensive: never print secret-bearing env values.
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            # Presence is fine; we never emit the value.
            pass


def _require_immutable_revision(revision: str) -> str:
    text = str(revision or "").strip()
    if not text:
        raise CliError("revision must be non-empty")
    # Fail closed on clearly mutable moving targets when not offline.
    mutable = {"main", "master", "latest", "head", "dev", "develop"}
    return text


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


def _build_limits(args: argparse.Namespace) -> QueryLimits:
    return QueryLimits(
        max_bytes=int(args.max_bytes),
        max_shards=int(args.max_shards),
        max_rows=int(args.max_rows),
        max_nodes=int(args.max_nodes),
        max_edges=int(args.max_edges),
        max_depth=int(args.max_depth),
        max_time_ms=int(args.max_time_ms),
    )


def _build_filters(args: argparse.Namespace) -> LegalFilters | None:
    payload: dict[str, Any] = {}
    if getattr(args, "title", None):
        payload["title"] = args.title
    if getattr(args, "section", None):
        payload["section"] = args.section
    if getattr(args, "citation", None):
        payload["citation"] = args.citation
    if getattr(args, "version", None):
        payload["version"] = args.version
    if getattr(args, "legal_id", None):
        payload["legal_id"] = args.legal_id
    if not payload:
        return None
    return LegalFilters.from_mapping(payload)


def _build_resolver(args: argparse.Namespace) -> ImmutableHubResolver:
    revision = _require_immutable_revision(args.revision)
    local_root = Path(args.local_root).expanduser().resolve() if args.local_root else None
    if local_root is not None:
        if not local_root.is_dir():
            raise CliError(f"local-root is not a directory: {local_root}")
        return ImmutableHubResolver(
            repo_id=args.repo_id,
            revision=revision,
            cache_dir=args.cache_dir,
            transport=LocalRootTransport(local_root),
            local_root=local_root,
            supported_schemas={
                "hf-graphrag-release/v1",
                "publicus-ir-graphrag/v2",
            },
        )
    if revision.lower() in {"main", "master", "latest", "head"}:
        raise CliError(
            "live Hub queries require an immutable revision pin "
            f"(got {revision!r}); use --local-root for offline fixtures"
        )
    try:
        return ImmutableHubResolver(
            repo_id=args.repo_id,
            revision=revision,
            cache_dir=args.cache_dir,
            supported_schemas={
                "hf-graphrag-release/v1",
                "publicus-ir-graphrag/v2",
            },
        )
    except (ResolverError, MutableRevisionError, TypeError, ValueError) as exc:
        raise CliError(f"failed to construct resolver: {exc}") from exc


def _fixture_embedder(dimension: int = 2):
    def _embed(text: str) -> list[float]:
        # Deterministic offline embedder: bag-of-characters hash into unit vector.
        if not isinstance(text, str) or not text:
            raise UscodeQueryInputError("query text required for embedding")
        acc = [0.0] * dimension
        for index, ch in enumerate(text.encode("utf-8")):
            acc[index % dimension] += float(ch)
        norm = math.sqrt(sum(v * v for v in acc)) or 1.0
        return [v / norm for v in acc]

    return _embed


def _build_client(args: argparse.Namespace) -> UscodeQueryClient:
    resolver = _build_resolver(args)
    limits = _build_limits(args)
    embedder = None
    if args.command in {"vector", "hybrid", "semantic-graph-walk"}:
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
                f"{args.command} requires --embedding or --local-root/--fixture-mode "
                "with a deterministic offline embedder"
            )
    fusion = None
    if args.command == "hybrid":
        fusion = FusionConfig(
            method=str(args.fusion_method),
            bm25_weight=float(args.bm25_weight),
            vector_weight=float(args.vector_weight),
            rrf_k=int(args.rrf_k),
        )
    return UscodeQueryClient(
        resolver,
        limits=limits,
        query_embedder=embedder,
        fusion=fusion,
    )


def _result_payload(result: UscodeQueryResult, *, include_trace: bool) -> dict[str, Any]:
    payload = result.to_dict()
    if not include_trace:
        payload.pop("fetch_trace", None)
    # Never emit env secrets even if accidentally nested.
    rendered = json.dumps(payload, sort_keys=True)
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and secret in rendered:
            raise CliError("refusing to emit secret-bearing output")
    return payload


def _print_human(result: UscodeQueryResult) -> None:
    print(
        f"mode={result.mode} complete={result.complete} "
        f"stop_reason={result.stop_reason} results={len(result.results)}"
    )
    for index, hit in enumerate(result.results[:20], start=1):
        cid = hit.get("entry_cid") or hit.get("node_cid") or hit.get("edge_cid")
        score = hit.get("score")
        print(f"  {index:02d}. score={score} id={cid}")


def _run_command(args: argparse.Namespace) -> int:
    client = _build_client(args)
    filters = _build_filters(args)
    top_k = int(getattr(args, "top_k", 5) or 5)
    try:
        if args.command == "bm25":
            result = client.bm25_search(
                args.query, top_k=top_k, filters=filters, hydrate=bool(args.hydrate)
            )
        elif args.command == "vector":
            embedding = _parse_float_list(args.embedding)
            result = client.vector_search(
                embedding if embedding is not None else args.query,
                top_k=top_k,
                filters=filters,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
            )
        elif args.command == "hybrid":
            result = client.hybrid_search(
                args.query,
                top_k=top_k,
                filters=filters,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
            )
        elif args.command == "neighbors":
            result = client.neighbors(
                args.node_cid,
                direction=str(args.direction),
                limit=int(args.limit),
                include_similarity=bool(args.include_similarity),
            )
        elif args.command == "graph-walk":
            result = client.graph_walk(
                args.start_node_cid,
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                direction=str(args.direction),
                include_similarity=bool(args.include_similarity),
            )
        elif args.command == "semantic-graph-walk":
            result = client.semantic_graph_walk(
                args.start_node_cid,
                query=args.query,
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                direction=str(args.direction),
                include_similarity=bool(args.include_similarity),
                beam=SemanticBeamConfig(
                    beam_width=int(args.beam_width),
                    candidate_centroids=int(args.candidate_centroids),
                ),
            )
        else:
            raise CliError(f"unknown command: {args.command}")
    except (UscodeQueryError, ResolverError, ValueError, TypeError) as exc:
        raise CliError(str(exc), code=1) from exc

    if args.json:
        payload = _result_payload(result, include_trace=bool(args.trace))
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        _print_human(result)
        if args.trace:
            sys.stdout.write(
                json.dumps(result.fetch_trace, indent=2, sort_keys=True) + "\n"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="query_uscode_hf.py",
        description="Direct Hugging Face US Code sparse GraphRAG query CLI (USCIR-028).",
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO, help="Pinned Hub repository id")
    parser.add_argument(
        "--revision",
        default=DEFAULT_REVISION,
        help="Immutable revision pin (required for live Hub; fixtures may use any)",
    )
    parser.add_argument("--cache-dir", default=None, help="Optional resolver cache directory")
    parser.add_argument(
        "--local-root",
        default=None,
        help="Offline release root (uses LocalRootTransport; no network)",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Enable deterministic offline embedder without live models",
    )
    parser.add_argument("--max-bytes", type=int, default=50_000_000)
    parser.add_argument("--max-shards", type=int, default=64)
    parser.add_argument("--max-rows", type=int, default=50_000)
    parser.add_argument("--max-nodes", type=int, default=256)
    parser.add_argument("--max-edges", type=int, default=1024)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--max-time-ms", type=int, default=60_000)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Include fetch_trace (JSON) / print trace after human summary",
    )
    parser.add_argument("--title", default=None, help="Legal filter: title")
    parser.add_argument("--section", default=None, help="Legal filter: section")
    parser.add_argument("--citation", default=None, help="Legal filter: citation text")
    parser.add_argument("--version", default=None, help="Legal filter: version id")
    parser.add_argument("--legal-id", default=None, help="Legal filter: durable legal_id")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_search_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--top-k", type=int, default=5)
        p.add_argument("--hydrate", action=argparse.BooleanOptionalAction, default=True)
        p.add_argument("--candidate-centroids", type=int, default=4)
        p.add_argument(
            "--embedding",
            default=None,
            help="Comma-separated query embedding (vector/hybrid/semantic)",
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

    p_n = sub.add_parser("neighbors", help="Bounded adjacency neighbors")
    p_n.add_argument("node_cid")
    p_n.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_n.add_argument("--limit", type=int, default=16)
    p_n.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=False,
    )

    p_gw = sub.add_parser("graph-walk", help="Structural bounded graph walk")
    p_gw.add_argument("start_node_cid")
    p_gw.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_gw.add_argument("--walk-depth", type=int, default=2)
    p_gw.add_argument("--walk-nodes", type=int, default=32)
    p_gw.add_argument("--walk-edges", type=int, default=64)
    p_gw.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=False,
    )

    p_sg = sub.add_parser(
        "semantic-graph-walk", help="Embedding-guided semantic beam walk"
    )
    p_sg.add_argument("start_node_cid")
    p_sg.add_argument("--query", default="", help="Optional text to embed for proximity")
    p_sg.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_sg.add_argument("--walk-depth", type=int, default=2)
    p_sg.add_argument("--walk-nodes", type=int, default=32)
    p_sg.add_argument("--walk-edges", type=int, default=64)
    p_sg.add_argument("--beam-width", type=int, default=4)
    p_sg.add_argument("--candidate-centroids", type=int, default=4)
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
