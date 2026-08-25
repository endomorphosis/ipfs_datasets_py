#!/usr/bin/env python3
"""Direct Hugging Face query CLI for Federal Register sparse GraphRAG (LCR-060).

Exposes the LCR-059 :class:`FederalRegisterQueryClient` as a package-facing
API and six CLI subcommands:

* ``bm25`` — lexicographic term-range BM25
* ``vector`` — evaluated-centroid dense retrieval
* ``hybrid`` — late fusion of compatible BM25 + vector rankings
* ``neighbors`` — bounded adjacency neighbors
* ``graph-walk`` — structural BFS (bounded graph)
* ``semantic-graph-walk`` — embedding-guided beam walk

Structured JSON and JSONL output, immutable repo/revision pins, agency /
date / document-type filters, resource budgets, revision-scoped cache
controls, and explicit offline replay are first-class. Queries never
default to a mutable ``main`` pin and never download the full index.

Offline fixture replay (no network, no accelerators)::

    python scripts/ops/legal_data/query_federal_register_hf.py \\
        --local-root PATH --fixture-mode --offline-replay --json --trace \\
        bm25 "foia agency" --agency EPA --document-type rule

Secrets are never printed. Malformed input fails closed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_sparse_query import (  # noqa: E402
    DEFAULT_BEAM_WIDTH,
    DEFAULT_BM25_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    QUERY_FILTERS,
    QUERY_MODES,
    FederalRegisterQueryClient,
    FederalRegisterQueryError,
    FederalRegisterQueryInputError,
    FederalRegisterQueryResult,
    FusionConfig,
    FusionConfigError,
    ImmutablePinError,
    LegalFilters,
    SemanticBeamConfig,
    query_replay_fingerprint,
    require_immutable_revision,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (  # noqa: E402
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_NODES,
    DEFAULT_MAX_ROWS,
    DEFAULT_MAX_SHARDS,
    DEFAULT_MAX_TIME_MS,
    DEFAULT_TOP_K,
    QueryInputError,
    QueryLimits,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    ImmutableHubResolver,
    LocalRootTransport,
    MutableRevisionError,
    ResolverError,
)

TASK_ID: Final = "LCR-060"
GOAL_ID: Final = "LCR-G120"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
ENGINE_TASK_ID: Final = "LCR-059"
DEFAULT_REPO: Final = "justicedao/ipfs_federal_register"
# Immutable 40-hex default; operators must pin explicitly. Never ``main``.
DEFAULT_REVISION: Final = "720668ae016cc400916dda884c9005e03618edfa"
DEFAULT_CANDIDATE_CENTROIDS: Final = 4
SUPPORTED_SCHEMAS: Final = frozenset(
    {
        "hf-graphrag-release/v1",
        "federal-register-ir-graphrag/v2",
        "publicus-ir-graphrag/v2",
    }
)
SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)
MUTABLE_REFS: Final = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "dev",
        "develop",
        "trunk",
        "nightly",
    }
)
CLI_MODE_ALIASES: Final = {
    "bm25": "bm25",
    "vector": "vector",
    "hybrid": "hybrid",
    "neighbors": "neighbors",
    "graph-walk": "graph_walk",
    "graph_walk": "graph_walk",
    "bounded-graph": "graph_walk",
    "semantic-graph-walk": "semantic_graph_walk",
    "semantic_graph_walk": "semantic_graph_walk",
    "semantic-graph": "semantic_graph_walk",
}
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
    for name in SECRET_ENV_NAMES:
        _ = os.environ.get(name)


def _assert_no_secret_payload(payload: Any) -> None:
    rendered = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, sort_keys=True, default=str)
    )
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and secret in rendered:
            raise CliError("refusing to emit secret-bearing output", code=1)


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
            raise FederalRegisterQueryInputError(
                "query text required for embedding"
            )
        acc = [0.0] * dimension
        for index, ch in enumerate(text.encode("utf-8")):
            acc[index % dimension] += float(ch)
        norm = math.sqrt(sum(v * v for v in acc)) or 1.0
        return [v / norm for v in acc]

    return _embed


def _pin_revision(revision: str) -> str:
    text = str(revision or "").strip()
    if not text:
        raise CliError("revision must be a non-empty immutable 40-hex pin")
    if text.casefold() in MUTABLE_REFS or text.casefold().startswith("refs/"):
        raise CliError(
            "refusing mutable revision "
            f"{revision!r}; Federal Register queries require an immutable pin"
        )
    try:
        return require_immutable_revision(text)
    except (ImmutablePinError, MutableRevisionError) as exc:
        raise CliError(str(exc)) from exc


def _build_limits(args: argparse.Namespace) -> QueryLimits:
    try:
        return QueryLimits(
            max_bytes=int(args.max_bytes),
            max_shards=int(args.max_shards),
            max_rows=int(args.max_rows),
            max_nodes=int(args.max_nodes),
            max_edges=int(args.max_edges),
            max_depth=int(args.max_depth),
            max_time_ms=int(args.max_time_ms),
        )
    except (TypeError, ValueError, QueryInputError) as exc:
        raise CliError(f"invalid resource budget: {exc}") from exc


def _build_filters(args: argparse.Namespace) -> LegalFilters | None:
    payload: dict[str, Any] = {}
    for key in (
        "agency",
        "date",
        "date_from",
        "date_to",
        "document_type",
        "citation",
        "legal_id",
        "source",
        "release_point",
    ):
        value = getattr(args, key, None)
        if value:
            payload[key] = value
    if not payload:
        return None
    try:
        return LegalFilters.from_mapping(payload)
    except FederalRegisterQueryInputError as exc:
        raise CliError(str(exc)) from exc


def _resolve_cache_dir(args: argparse.Namespace) -> str | Path | None:
    if bool(getattr(args, "no_cache", False)) and getattr(args, "cache_dir", None):
        raise CliError("--no-cache cannot be combined with --cache-dir")
    if bool(getattr(args, "no_cache", False)):
        return Path(tempfile.mkdtemp(prefix="fr-query-nocache-"))
    cache_dir = getattr(args, "cache_dir", None)
    if bool(getattr(args, "reset_cache", False)):
        if not cache_dir:
            raise CliError("--reset-cache requires --cache-dir")
        target = Path(cache_dir).expanduser()
        if target.exists():
            shutil.rmtree(target)
    return cache_dir


def open_query_client(
    *,
    repo_id: str = DEFAULT_REPO,
    revision: str = DEFAULT_REVISION,
    local_root: Path | str | None = None,
    cache_dir: Path | str | None = None,
    limits: QueryLimits | Mapping[str, Any] | None = None,
    query_embedder: Any = None,
    fusion: FusionConfig | Mapping[str, Any] | None = None,
    no_cache: bool = False,
    reset_cache: bool = False,
) -> FederalRegisterQueryClient:
    """Construct a pinned Federal Register query client (package API)."""

    pin = _pin_revision(revision)
    root: Path | None = None
    if local_root is not None:
        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise CliError(f"local-root is not a directory: {root}")

    resolved_cache: Path | str | None = cache_dir
    if no_cache:
        if cache_dir is not None:
            raise CliError("--no-cache cannot be combined with --cache-dir")
        resolved_cache = Path(tempfile.mkdtemp(prefix="fr-query-nocache-"))
    elif reset_cache:
        if cache_dir is None:
            raise CliError("--reset-cache requires --cache-dir")
        target = Path(cache_dir).expanduser()
        if target.exists():
            shutil.rmtree(target)
        resolved_cache = cache_dir

    kwargs: dict[str, Any] = {
        "repo_id": repo_id,
        "revision": pin,
        "cache_dir": resolved_cache,
        "supported_schemas": set(SUPPORTED_SCHEMAS),
    }
    if root is not None:
        kwargs["transport"] = LocalRootTransport(root)
        kwargs["local_root"] = root

    try:
        resolver = ImmutableHubResolver(**kwargs)
    except (ResolverError, MutableRevisionError, TypeError, ValueError) as exc:
        raise CliError(f"failed to construct resolver: {exc}") from exc

    if isinstance(limits, QueryLimits) or limits is None:
        query_limits = limits
    elif isinstance(limits, Mapping):
        try:
            query_limits = QueryLimits(
                **{
                    key: limits[key]
                    for key in (
                        "max_bytes",
                        "max_shards",
                        "max_rows",
                        "max_nodes",
                        "max_edges",
                        "max_depth",
                        "max_time_ms",
                    )
                    if key in limits
                }
            )
        except (TypeError, ValueError, QueryInputError) as exc:
            raise CliError(f"invalid resource budget: {exc}") from exc
    else:
        raise CliError("limits must be QueryLimits or a mapping")

    try:
        return FederalRegisterQueryClient(
            resolver,
            limits=query_limits,
            query_embedder=query_embedder,
            fusion=fusion,
        )
    except (
        FederalRegisterQueryError,
        ImmutablePinError,
        FusionConfigError,
        TypeError,
        ValueError,
    ) as exc:
        raise CliError(f"failed to construct query client: {exc}") from exc


def _build_client(args: argparse.Namespace) -> FederalRegisterQueryClient:
    command = str(args.command)
    embedder = None
    needs_embedder = command in {
        "vector",
        "hybrid",
        "semantic-graph-walk",
        "semantic_graph_walk",
        "semantic-graph",
    }
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

    fusion = None
    if command == "hybrid":
        try:
            fusion = FusionConfig(
                method=str(args.fusion_method),
                bm25_weight=float(args.bm25_weight),
                vector_weight=float(args.vector_weight),
                rrf_k=int(args.rrf_k),
            )
        except (FusionConfigError, TypeError, ValueError) as exc:
            raise CliError(str(exc)) from exc

    ns = argparse.Namespace(
        cache_dir=args.cache_dir,
        no_cache=bool(getattr(args, "no_cache", False)),
        reset_cache=bool(getattr(args, "reset_cache", False)),
        max_bytes=args.max_bytes,
        max_shards=args.max_shards,
        max_rows=args.max_rows,
        max_nodes=args.max_nodes,
        max_edges=args.max_edges,
        max_depth=args.max_depth,
        max_time_ms=args.max_time_ms,
    )
    return open_query_client(
        repo_id=str(args.repo_id),
        revision=str(args.revision),
        local_root=args.local_root,
        cache_dir=_resolve_cache_dir(ns),
        limits=_build_limits(args),
        query_embedder=embedder,
        fusion=fusion,
    )


def execute_query(
    command: str,
    client: FederalRegisterQueryClient,
    args: argparse.Namespace,
) -> FederalRegisterQueryResult:
    """Dispatch a CLI/package command onto :class:`FederalRegisterQueryClient`."""

    mode = CLI_MODE_ALIASES.get(command, command)
    if mode not in QUERY_MODES:
        raise CliError(f"unknown command: {command}")
    if mode in {"bm25", "hybrid"} and not str(getattr(args, "query", "") or "").strip():
        raise CliError("query must be a non-empty string")
    filters = _build_filters(args)
    top_k = int(getattr(args, "top_k", DEFAULT_TOP_K) or DEFAULT_TOP_K)
    embedding = _parse_float_list(getattr(args, "embedding", None))
    try:
        if mode == "bm25":
            return client.bm25_search(
                args.query,
                top_k=top_k,
                filters=filters,
                hydrate=bool(args.hydrate),
            )
        if mode == "vector":
            return client.vector_search(
                args.query or "",
                query_vector=embedding,
                top_k=top_k,
                filters=filters,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
            )
        if mode == "hybrid":
            return client.hybrid_search(
                args.query,
                query_vector=embedding,
                top_k=top_k,
                filters=filters,
                hydrate=bool(args.hydrate),
                candidate_centroids=int(args.candidate_centroids),
            )
        if mode == "neighbors":
            return client.neighbors(
                args.node_cid,
                direction=str(args.direction),
                limit=int(args.limit),
                include_similarity=bool(args.include_similarity),
            )
        if mode == "graph_walk":
            return client.graph_walk(
                args.start_node_cid,
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                direction=str(args.direction),
                include_similarity=bool(args.include_similarity),
            )
        return client.semantic_graph_walk(
            args.start_node_cid,
            query=args.query or "",
            query_vector=embedding,
            direction=str(args.direction),
            include_similarity=bool(args.include_similarity),
            beam=SemanticBeamConfig(
                max_depth=int(args.walk_depth),
                max_nodes=int(args.walk_nodes),
                max_edges=int(args.walk_edges),
                beam_width=int(args.beam_width),
                candidate_centroids=int(args.candidate_centroids),
            ),
        )
    except (
        FederalRegisterQueryInputError,
        FusionConfigError,
        ImmutablePinError,
    ) as exc:
        raise CliError(str(exc), code=2) from exc
    except (FederalRegisterQueryError, ResolverError, ValueError, TypeError) as exc:
        raise CliError(str(exc), code=1) from exc


def package_query_result(
    result: FederalRegisterQueryResult | Mapping[str, Any],
    *,
    client: FederalRegisterQueryClient | None = None,
    include_trace: bool = True,
    offline_replay: bool = False,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Render a structured query payload with pin, budgets, and optional replay."""

    if isinstance(result, FederalRegisterQueryResult):
        payload = result.to_dict()
        ordered = list(result.ordered_result_cids())
        fingerprint_source: FederalRegisterQueryResult | Mapping[str, Any] = result
    elif isinstance(result, Mapping):
        payload = dict(result)
        ordered = list(payload.get("ordered_result_cids") or [])
        if not ordered:
            for item in payload.get("results") or ():
                if not isinstance(item, Mapping):
                    continue
                for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
                    if key in item and item[key] is not None:
                        ordered.append(str(item[key]))
                        break
        fingerprint_source = payload
    else:
        raise CliError("query result must be a mapping")

    payload["ordered_result_cids"] = ordered
    payload["full_index_downloaded"] = False
    payload["interface_task_id"] = TASK_ID
    payload["interface_goal_id"] = GOAL_ID
    payload["program_id"] = PROGRAM_ID
    payload["engine_task_id"] = payload.get("task_id") or ENGINE_TASK_ID
    if client is not None:
        payload["pin"] = {
            "mutable_rejected": True,
            "offline": client.resolver.local_root is not None,
            "repo_id": client.resolver.repo_id,
            "revision": client.resolver.revision,
        }
    if not include_trace:
        payload.pop("fetch_trace", None)
    if offline_replay:
        fingerprint = query_replay_fingerprint(fingerprint_source)
        payload["offline_replay"] = True
        payload["replay_fingerprint"] = fingerprint
        if expected_fingerprint:
            expected = str(expected_fingerprint).strip().lower()
            if fingerprint.lower() != expected:
                raise CliError(
                    "offline replay fingerprint mismatch: "
                    f"got {fingerprint}, expected {expected}",
                    code=1,
                )
    _assert_no_secret_payload(payload)
    return payload


def emit_jsonl(payload: Mapping[str, Any]) -> None:
    """Write a deterministic JSONL stream: header, hits, optional replay."""

    header = {
        key: value
        for key, value in payload.items()
        if key not in {"results", "edges"}
    }
    header["kind"] = "result"
    sys.stdout.write(
        json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n"
    )
    for index, hit in enumerate(payload.get("results") or ()):
        record = {"index": index, "kind": "hit"}
        if isinstance(hit, Mapping):
            record["hit"] = dict(hit)
        else:
            record["value"] = hit
        sys.stdout.write(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        )
    for index, edge in enumerate(payload.get("edges") or ()):
        record = {
            "edge": dict(edge) if isinstance(edge, Mapping) else edge,
            "index": index,
            "kind": "edge",
        }
        sys.stdout.write(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        )
    if payload.get("replay_fingerprint"):
        sys.stdout.write(
            json.dumps(
                {
                    "kind": "replay",
                    "offline_replay": True,
                    "replay_fingerprint": payload["replay_fingerprint"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


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
        cid = hit.get("entry_cid") or hit.get("node_cid") or hit.get("chunk_cid")
        score = hit.get("score")
        print(f"  {index:02d}. score={score} id={cid}")


def query_surface() -> dict[str, Any]:
    """Describe the public CLI/package query surface (no I/O)."""

    return {
        "cache_controls": ["cache-dir", "no-cache", "reset-cache"],
        "engine_task_id": ENGINE_TASK_ID,
        "filter_fields": list(QUERY_FILTERS),
        "formats": ["json", "jsonl", "text"],
        "full_index_download": False,
        "goal_id": GOAL_ID,
        "modes": list(QUERY_MODES),
        "mutable_main_default": False,
        "offline_replay": True,
        "pins": {
            "dataset_repo_id": DEFAULT_REPO,
            "mutable_rejected": True,
            "revision": DEFAULT_REVISION,
        },
        "program_id": PROGRAM_ID,
        "subcommands": list(SUBCOMMANDS),
        "task_id": TASK_ID,
    }


def _run_command(args: argparse.Namespace) -> int:
    if bool(getattr(args, "offline_replay", False)) and not args.local_root:
        raise CliError("--offline-replay requires --local-root")
    if getattr(args, "expected_fingerprint", None) and not bool(
        getattr(args, "offline_replay", False)
    ):
        raise CliError("--expected-fingerprint requires --offline-replay")
    if bool(getattr(args, "json", False)) and bool(getattr(args, "jsonl", False)):
        raise CliError("--json and --jsonl are mutually exclusive")

    client = _build_client(args)
    result = execute_query(str(args.command), client, args)
    payload = package_query_result(
        result,
        client=client,
        include_trace=bool(args.trace),
        offline_replay=bool(getattr(args, "offline_replay", False)),
        expected_fingerprint=getattr(args, "expected_fingerprint", None),
    )
    if args.jsonl:
        emit_jsonl(payload)
    elif args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        _print_human(payload)
        if args.trace:
            sys.stdout.write(
                json.dumps(payload.get("fetch_trace") or {}, indent=2, sort_keys=True)
                + "\n"
            )
        if payload.get("replay_fingerprint"):
            print(f"replay_fingerprint={payload['replay_fingerprint']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="query_federal_register_hf.py",
        description=(
            "Direct Hugging Face Federal Register sparse GraphRAG query CLI "
            "(LCR-060). Modes: bm25, vector, hybrid, neighbors, graph-walk, "
            "semantic-graph-walk. Structured JSON and JSONL output, immutable "
            "repo/revision pins, agency/date/document-type filters, resource "
            "budgets, cache controls, and explicit offline replay. Never "
            "defaults to a mutable main pin."
        ),
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO, help="Pinned Hub repository id")
    parser.add_argument(
        "--revision",
        default=DEFAULT_REVISION,
        help="Immutable 40-hex Hub commit SHA (required; never main)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Revision-scoped resolver cache directory",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Use a throwaway cache directory for this process",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="Delete --cache-dir before querying (requires --cache-dir)",
    )
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
    parser.add_argument(
        "--offline-replay",
        action="store_true",
        help="Explicit offline replay: require --local-root and emit fingerprint",
    )
    parser.add_argument(
        "--expected-fingerprint",
        default=None,
        help="Fail when the offline replay fingerprint does not match",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-shards", type=int, default=DEFAULT_MAX_SHARDS)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    parser.add_argument("--max-edges", type=int, default=DEFAULT_MAX_EDGES)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-time-ms", type=int, default=DEFAULT_MAX_TIME_MS)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Emit structured JSON")
    output.add_argument(
        "--jsonl",
        action="store_true",
        help="Emit JSONL (header, hits, optional replay record)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Include fetch_trace (JSON/JSONL) / print trace after human summary",
    )
    parser.add_argument("--agency", default=None, help="Filter: issuing agency")
    parser.add_argument("--date", default=None, help="Filter: publication date (YYYY-MM-DD)")
    parser.add_argument("--date-from", default=None, dest="date_from")
    parser.add_argument("--date-to", default=None, dest="date_to")
    parser.add_argument(
        "--document-type",
        default=None,
        dest="document_type",
        help="Filter: rule / proposed_rule / notice / ...",
    )
    parser.add_argument("--citation", default=None, help="Filter: citation text")
    parser.add_argument("--legal-id", default=None, dest="legal_id")
    parser.add_argument("--source", default=None, help="Filter: source")
    parser.add_argument("--release-point", default=None, dest="release_point")

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
    p_hyb.add_argument("--bm25-weight", type=float, default=DEFAULT_BM25_WEIGHT)
    p_hyb.add_argument("--vector-weight", type=float, default=DEFAULT_VECTOR_WEIGHT)
    p_hyb.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)

    p_n = sub.add_parser("neighbors", help="Bounded adjacency neighbors")
    p_n.add_argument("node_cid")
    p_n.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p_n.add_argument("--limit", type=int, default=16)
    p_n.add_argument(
        "--include-similarity",
        action=argparse.BooleanOptionalAction,
        default=True,
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
        default=True,
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
    p_sg.add_argument("--beam-width", type=int, default=DEFAULT_BEAM_WIDTH)
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
    try:
        _reject_secrets_in_argv(argv_list)
        _assert_no_secret_env_echo()
        parser = build_parser()
        try:
            args = parser.parse_args(argv_list)
        except SystemExit as exc:
            return int(exc.code or 0)
        return _run_command(args)
    except CliError as exc:
        return int(exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
