#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Knowledge-graph CLI surface over GraphService (KGP-018).

Production entry points (``ipfs-datasets graph …``) call into this module.
Every operation resolves an explicit :class:`GraphTarget` and opens a
:class:`~ipfs_datasets_py.knowledge_graphs.client.Client` against durable
catalog + payload storage paths so independent processes reopen the same
graphs (OSR-6).

Commands
--------
create, list, describe, write, query, transaction (begin|commit|rollback),
branch, delete, import, export, verify  (plus ``open`` for snapshot handles).

Selectors
---------
``--target kg://…`` or ``--tenant`` / ``--graph`` / ``--branch`` / ``--revision``
plus store selectors ``--catalog`` / ``--store`` (or env
``IPFS_DATASETS_KG_CATALOG`` / ``IPFS_DATASETS_KG_STORE``).

Output
------
``--format json|table`` (global ``--json`` forces JSON). Stable exit codes:

* 0 — success
* 1 — lifecycle / typed service error
* 2 — usage / invalid arguments
* 3 — module unavailable or unexpected internal failure
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

# ---------------------------------------------------------------------------
# Exit codes (stable contract)
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3

DEFAULT_BRANCH = "main"
# Must pass GraphTarget slug validation (cannot lead with underscore).
LIST_WILDCARD_GRAPH = "list"

ENV_CATALOG = "IPFS_DATASETS_KG_CATALOG"
ENV_STORE = "IPFS_DATASETS_KG_STORE"

GRAPH_SUBCOMMANDS = frozenset(
    {
        "create",
        "list",
        "describe",
        "write",
        "query",
        "transaction",
        "branch",
        "delete",
        "import",
        "export",
        "verify",
        "open",
        # aliases
        "tx-begin",
        "tx-commit",
        "tx-rollback",
        "begin_tx",
        "commit_tx",
        "rollback_tx",
        "help",
        "--help",
        "-h",
    }
)

HELP_TEXT = """\
ipfs-datasets graph — GraphService knowledge-graph commands (KGP-018)

Usage:
  ipfs-datasets graph <command> [options]

Commands:
  create       Register a graph identity (tenant + graph + branch)
  list         List graphs for a tenant
  describe     Catalog metadata + branch heads
  write        Stage and commit entity/relationship mutations
  query        Run a bounded query (scan / cypher-lite) against a snapshot
  transaction  Explicit transaction boundaries (begin|commit|rollback)
  branch       Create or update a named branch pointer
  delete       Tombstone a graph or branch
  import       Import entities/relationships from JSON file or stdin
  export       Export a revision snapshot as JSON
  verify       Verify snapshot presence, counts, and checksum
  open         Resolve a target to an immutable revision handle

Target selectors (every request names a graph target):
  --target kg://<tenant>/<graph>[/branches/<branch>|/revisions/<rev>]
  --tenant TENANT --graph GRAPH [--branch BRANCH | --revision REV]
  --profile parquet|ipfs_ipld|ipfs_kit|hybrid

Store selectors (durable reopen across processes):
  --catalog PATH   Catalog SQLite path (env: IPFS_DATASETS_KG_CATALOG)
  --store PATH     Payload storage path (env: IPFS_DATASETS_KG_STORE)

Output:
  --format json|table   Result presentation (default: table; --json forces json)
  --stream              Stream query pages as NDJSON (json format)
  --page-size N         Streaming page size (default: 100)

Common options:
  --idempotency-key KEY Required for create/write/commit/import retries
  --params JSON         Extra operation params object
  --file PATH           Input file for write/import (- = stdin)
  --stdin               Read payload from stdin
  --output PATH         Output path for export (- = stdout)
  --cypher / --query    Query text (query command)
  --language LANG       Query language (scan|cypher|cypher-lite; default scan)
  --tx-id ID            Transaction id (commit/rollback/write into tx)
  --entities JSON       Entity list for write
  --relationships JSON  Relationship list for write
  --from-branch NAME    Source branch for branch command
  --from-revision REV   Source revision for branch command
  --reason TEXT         Delete reason

Exit codes:
  0 success | 1 service/lifecycle error | 2 usage | 3 unavailable/internal

Examples:
  ipfs-datasets graph create --catalog /tmp/kg.sqlite --tenant acme --graph skills \\
      --branch main --idempotency-key create-1 --format json
  ipfs-datasets graph write --catalog /tmp/kg.sqlite --target kg://acme/skills/branches/main \\
      --idempotency-key w1 --entities '[{"id":"e1","type":"Person","name":"Ada"}]' --format json
  ipfs-datasets graph query --catalog /tmp/kg.sqlite --tenant acme --graph skills \\
      --branch main --language scan --format json
  ipfs-datasets graph export --catalog /tmp/kg.sqlite --tenant acme --graph skills \\
      --branch main --format json
"""


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _json_loads(value: Any, *, what: str = "value") -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON for {what}: {exc}") from exc


def _read_payload(
    *,
    file_path: Optional[str],
    use_stdin: bool,
    stdin: TextIO = sys.stdin,
) -> Any:
    """Read JSON payload from file, stdin, or return None."""
    if file_path is not None:
        if file_path in {"-", "/dev/stdin"}:
            raw = stdin.read()
        else:
            raw = Path(file_path).read_text(encoding="utf-8")
        raw = raw.strip()
        if not raw:
            return None
        return json.loads(raw)
    if use_stdin:
        if stdin.isatty():
            raise ValueError("stdin requested but is a TTY; pipe JSON or use --file")
        raw = stdin.read().strip()
        if not raw:
            return None
        return json.loads(raw)
    return None


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _checksum(obj: Any) -> str:
    return hashlib.sha256(_canonical_dumps(obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def _emit_json(payload: Any, *, stream: TextIO = sys.stdout) -> None:
    stream.write(json.dumps(payload, indent=2, allow_nan=False, sort_keys=False))
    stream.write("\n")
    stream.flush()


def _emit_ndjson(payload: Any, *, stream: TextIO = sys.stdout) -> None:
    stream.write(json.dumps(payload, allow_nan=False, sort_keys=False))
    stream.write("\n")
    stream.flush()


def _table_lines_from_mapping(data: Mapping[str, Any], *, indent: int = 0) -> List[str]:
    pad = "  " * indent
    lines: List[str] = []
    for key, value in data.items():
        if isinstance(value, Mapping):
            lines.append(f"{pad}{key}:")
            lines.extend(_table_lines_from_mapping(value, indent=indent + 1))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
            elif all(not isinstance(x, (dict, list)) for x in value):
                lines.append(f"{pad}{key}: {', '.join(str(x) for x in value)}")
            else:
                lines.append(f"{pad}{key}:")
                for i, item in enumerate(value):
                    if isinstance(item, Mapping):
                        lines.append(f"{pad}  - [{i}]")
                        lines.extend(
                            _table_lines_from_mapping(item, indent=indent + 2)
                        )
                    else:
                        lines.append(f"{pad}  - {item}")
        else:
            lines.append(f"{pad}{key}: {value}")
    return lines


def _render_table_lifecycle(envelope: Mapping[str, Any]) -> str:
    status = envelope.get("status")
    op = envelope.get("operation")
    lines = [f"status: {status}", f"operation: {op}"]
    if envelope.get("request_id"):
        lines.append(f"request_id: {envelope['request_id']}")
    target = envelope.get("target")
    if isinstance(target, Mapping):
        lines.append(f"target: {target.get('uri') or target}")
    if status == "success":
        result = envelope.get("result")
        if isinstance(result, Mapping):
            # Query envelopes: render as a simple table when columns/rows present.
            if "columns" in result and "rows" in result:
                cols = list(result.get("columns") or [])
                rows = list(result.get("rows") or [])
                lines.append(f"revision: {result.get('revision')}")
                lines.append(f"schema: {result.get('schema')}")
                lines.append(f"row_count: {result.get('row_count', len(rows))}")
                if cols:
                    lines.append(" | ".join(str(c) for c in cols))
                    lines.append("-+-".join("-" * max(3, len(str(c))) for c in cols))
                for row in rows:
                    if isinstance(row, (list, tuple)):
                        lines.append(" | ".join(str(c) for c in row))
                    else:
                        lines.append(str(row))
                if result.get("truncated"):
                    lines.append("truncated: true")
            else:
                lines.append("result:")
                lines.extend(_table_lines_from_mapping(result, indent=1))
        elif result is not None:
            lines.append(f"result: {result}")
        warnings = envelope.get("warnings") or []
        if warnings:
            lines.append("warnings: " + "; ".join(str(w) for w in warnings))
    else:
        err = envelope.get("error") or {}
        if isinstance(err, Mapping):
            lines.append(f"error.code: {err.get('code')}")
            lines.append(f"error.message: {err.get('message')}")
            if err.get("retryable") is not None:
                lines.append(f"error.retryable: {err.get('retryable')}")
            details = err.get("details")
            if details:
                lines.append(f"error.details: {json.dumps(details, sort_keys=True)}")
        else:
            lines.append(f"error: {err}")
    return "\n".join(lines) + "\n"


def emit_lifecycle_result(
    envelope: Mapping[str, Any],
    *,
    fmt: str,
    stream: TextIO = sys.stdout,
) -> None:
    if fmt == "json":
        _emit_json(envelope, stream=stream)
    else:
        stream.write(_render_table_lifecycle(envelope))
        stream.flush()


def emit_usage_error(message: str, *, stream: TextIO = sys.stderr) -> None:
    stream.write(f"Error: {message}\n")
    stream.write("For help: ipfs-datasets graph --help\n")
    stream.flush()


# ---------------------------------------------------------------------------
# Target / store resolution
# ---------------------------------------------------------------------------


def resolve_catalog_store(
    kwargs: Mapping[str, Any],
) -> Tuple[Path, Optional[Path]]:
    catalog = (
        kwargs.get("catalog")
        or kwargs.get("catalog_path")
        or kwargs.get("catalog-path")
        or os.environ.get(ENV_CATALOG)
    )
    store = (
        kwargs.get("store")
        or kwargs.get("storage_path")
        or kwargs.get("storage-path")
        or kwargs.get("store_path")
        or kwargs.get("store-path")
        or os.environ.get(ENV_STORE)
    )
    if not catalog:
        raise ValueError(
            "catalog path required (--catalog PATH or env "
            f"{ENV_CATALOG})"
        )
    catalog_path = Path(str(catalog)).expanduser()
    storage_path = Path(str(store)).expanduser() if store else None
    return catalog_path, storage_path


def resolve_target(
    kwargs: Mapping[str, Any],
    *,
    require_graph: bool = True,
    default_branch: Optional[str] = None,
    for_list: bool = False,
):
    """Build a GraphTarget from CLI kwargs.

    Returns (GraphTarget, extra_notes). Raises ValueError on usage errors.
    """
    from ipfs_datasets_py.knowledge_graphs import GraphTarget
    from ipfs_datasets_py.knowledge_graphs.service import GraphTargetError

    target_uri = kwargs.get("target") or kwargs.get("uri")
    tenant = kwargs.get("tenant")
    graph_id = (
        kwargs.get("graph")
        or kwargs.get("graph_id")
        or kwargs.get("graph-id")
        or kwargs.get("id")
    )
    branch = kwargs.get("branch")
    revision = kwargs.get("revision") or kwargs.get("rev")
    profile = (
        kwargs.get("profile")
        or kwargs.get("storage_profile")
        or kwargs.get("storage-profile")
    )

    try:
        if target_uri:
            t = GraphTarget.from_uri(str(target_uri), storage_profile=profile)
            # Allow CLI overrides on top of URI.
            if tenant and tenant != t.tenant:
                raise ValueError("--tenant conflicts with --target URI")
            if graph_id and graph_id != t.graph_id:
                raise ValueError("--graph conflicts with --target URI")
            if branch is not None and revision is not None:
                raise ValueError("--branch and --revision are mutually exclusive")
            if branch is not None:
                t = t.with_branch(str(branch))
            if revision is not None:
                t = t.with_revision(str(revision))
            if profile is not None and t.storage_profile != profile:
                t = t.with_profile(str(profile))
            return t

        if not tenant:
            raise ValueError("--target or --tenant is required")
        if for_list and not graph_id:
            graph_id = LIST_WILDCARD_GRAPH
        if require_graph and not graph_id:
            raise ValueError("--graph (or --target) is required")
        if not graph_id:
            graph_id = LIST_WILDCARD_GRAPH
        if branch is not None and revision is not None:
            raise ValueError("--branch and --revision are mutually exclusive")
        if default_branch is not None and branch is None and revision is None:
            branch = default_branch
        return GraphTarget(
            tenant=str(tenant),
            graph_id=str(graph_id),
            branch=str(branch) if branch is not None else None,
            revision=str(revision) if revision is not None else None,
            storage_profile=str(profile) if profile is not None else None,
        )
    except GraphTargetError as exc:
        raise ValueError(f"{exc.code}: {exc}") from exc


def _open_client(catalog_path: Path, storage_path: Optional[Path]):
    from ipfs_datasets_py.knowledge_graphs import Client

    return Client.open(catalog_path, storage_path=storage_path)


def _lifecycle_to_dict(result) -> Dict[str, Any]:
    return result.to_json_dict()


def _exit_for_result(result) -> int:
    return EXIT_OK if result.ok else EXIT_ERROR


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _merge_params(
    kwargs: Mapping[str, Any],
    base: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = dict(base or {})
    raw = kwargs.get("params")
    if raw is not None:
        loaded = _json_loads(raw, what="--params")
        if loaded is None:
            pass
        elif not isinstance(loaded, Mapping):
            raise ValueError("--params must be a JSON object")
        else:
            params.update(dict(loaded))
    return params


def _idempotency_key(kwargs: Mapping[str, Any], *, required: bool) -> Optional[str]:
    key = (
        kwargs.get("idempotency_key")
        or kwargs.get("idempotency-key")
        or kwargs.get("idem")
    )
    if key:
        return str(key)
    if required:
        raise ValueError("--idempotency-key is required for this operation")
    return None


def cmd_create(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(kwargs, require_graph=True, default_branch=DEFAULT_BRANCH)
    params = _merge_params(kwargs)
    if target.storage_profile and "storage_profile" not in params:
        params["storage_profile"] = target.storage_profile
    for src, dst in (
        ("graph_kind", "graph_kind"),
        ("graph-kind", "graph_kind"),
        ("kind", "graph_kind"),
        ("metadata", "metadata"),
    ):
        if src in kwargs and dst not in params:
            val = kwargs[src]
            if dst == "metadata":
                val = _json_loads(val, what="--metadata") or {}
            params[dst] = val
    key = _idempotency_key(kwargs, required=False) or f"cli-create-{uuid.uuid4().hex}"
    result = client.create(target, idempotency_key=key, params=params or None)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_list(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(kwargs, require_graph=False, for_list=True)
    params = _merge_params(kwargs)
    graph_filter = (
        kwargs.get("graph")
        or kwargs.get("graph_id")
        or kwargs.get("graph-id")
        or params.get("graph_id")
    )
    if graph_filter and graph_filter != LIST_WILDCARD_GRAPH:
        params["graph_id"] = graph_filter
        params["filter_by_target_graph"] = True
    if kwargs.get("include_tombstoned") or kwargs.get("include-tombstoned"):
        params["include_tombstoned"] = True
    result = client.list(target, params=params or None)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_describe(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(kwargs, require_graph=True)
    params = _merge_params(kwargs)
    if kwargs.get("include_tombstoned_branches") or kwargs.get(
        "include-tombstoned-branches"
    ):
        params["include_tombstoned_branches"] = True
    result = client.describe(target, params=params or None)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_open(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    params = _merge_params(kwargs)
    result = client.open_graph(target, params=params or None)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def _collect_mutations(kwargs: Mapping[str, Any], stdin: TextIO) -> Dict[str, Any]:
    params = _merge_params(kwargs)
    file_path = kwargs.get("file") or kwargs.get("input")
    use_stdin = bool(kwargs.get("stdin"))
    payload = _read_payload(
        file_path=str(file_path) if file_path is not None else None,
        use_stdin=use_stdin,
        stdin=stdin,
    )
    if payload is not None:
        if isinstance(payload, Mapping):
            for key in ("entities", "relationships", "delete_entity_ids"):
                if key in payload and key not in params:
                    params[key] = payload[key]
            # bare {id,type,...} entity object
            if "entities" not in params and (
                "id" in payload or "type" in payload
            ):
                params["entities"] = [dict(payload)]
        elif isinstance(payload, list):
            params.setdefault("entities", payload)
        else:
            raise ValueError("stdin/file payload must be a JSON object or array")

    if "entities" in kwargs:
        ents = _json_loads(kwargs["entities"], what="--entities")
        if ents is not None:
            params["entities"] = ents
    if "relationships" in kwargs:
        rels = _json_loads(kwargs["relationships"], what="--relationships")
        if rels is not None:
            params["relationships"] = rels
    if "delete_entity_ids" in kwargs or "delete-entity-ids" in kwargs:
        raw = kwargs.get("delete_entity_ids") or kwargs.get("delete-entity-ids")
        dels = _json_loads(raw, what="--delete-entity-ids")
        if dels is not None:
            params["delete_entity_ids"] = dels

    tx_id = kwargs.get("tx_id") or kwargs.get("tx-id") or kwargs.get("transaction_id")
    if tx_id:
        params["transaction_id"] = str(tx_id)
    if kwargs.get("force_empty") or kwargs.get("force-empty"):
        params["force_empty"] = True
    if kwargs.get("allow_empty") or kwargs.get("allow-empty"):
        params["allow_empty"] = True
    return params


def _tx_state_dir(client) -> Path:
    """Directory for CLI durable transaction staging (cross-process)."""
    cfg = getattr(client, "config", None)
    if cfg is not None and getattr(cfg, "storage_path", None):
        base = Path(cfg.storage_path)
    elif cfg is not None and getattr(cfg, "catalog_path", None):
        base = Path(cfg.catalog_path).parent / f"{Path(cfg.catalog_path).stem}.payloads"
    else:
        base = Path(os.environ.get(ENV_STORE) or Path.cwd() / "kg_payloads")
    path = base / ".cli_transactions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tx_state_path(client, tx_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tx_id)
    return _tx_state_dir(client) / f"{safe}.json"


def _load_tx_state(client, tx_id: str) -> Optional[Dict[str, Any]]:
    path = _tx_state_path(client, tx_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_tx_state(client, state: Mapping[str, Any]) -> Path:
    tx_id = str(state["transaction_id"])
    path = _tx_state_path(client, tx_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(dict(state), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def _delete_tx_state(client, tx_id: str) -> None:
    path = _tx_state_path(client, tx_id)
    try:
        path.unlink(missing_ok=True)  # type: ignore[call-arg]
    except TypeError:
        if path.exists():
            path.unlink()


def cmd_write(
    client, kwargs: Mapping[str, Any], *, stdin: TextIO = sys.stdin
) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    params = _collect_mutations(kwargs, stdin)
    key = _idempotency_key(kwargs, required=True)
    tx_id = params.get("transaction_id")
    if tx_id:
        # Prefer durable CLI staging so independent processes can participate.
        state = _load_tx_state(client, str(tx_id))
        if state is not None:
            if state.get("state") != "open":
                envelope = {
                    "contract_version": "kg-service-contract/v1",
                    "status": "error",
                    "operation": "write",
                    "target": target.to_json_dict(),
                    "result": None,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": (
                            f"transaction is not open (state={state.get('state')})"
                        ),
                        "retryable": False,
                        "details": {"transaction_id": tx_id},
                        "cause_code": None,
                    },
                    "warnings": [],
                    "request_id": None,
                    "authorization_receipt_ref": None,
                }
                return envelope, EXIT_ERROR
            if (
                state.get("tenant") != target.tenant
                or state.get("graph_id") != target.graph_id
                or state.get("branch") != (target.branch or DEFAULT_BRANCH)
            ):
                envelope = {
                    "contract_version": "kg-service-contract/v1",
                    "status": "error",
                    "operation": "write",
                    "target": target.to_json_dict(),
                    "result": None,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "transaction target mismatch",
                        "retryable": False,
                        "details": {"transaction_id": tx_id},
                        "cause_code": None,
                    },
                    "warnings": [],
                    "request_id": None,
                    "authorization_receipt_ref": None,
                }
                return envelope, EXIT_ERROR
            staged_e = list(state.get("entities") or [])
            staged_r = list(state.get("relationships") or [])
            staged_d = list(state.get("delete_entity_ids") or [])
            for e in params.get("entities") or []:
                staged_e.append(dict(e) if isinstance(e, Mapping) else e)
            for r in params.get("relationships") or []:
                staged_r.append(dict(r) if isinstance(r, Mapping) else r)
            for d in params.get("delete_entity_ids") or []:
                staged_d.append(d)
            mutation_count = len(staged_e) + len(staged_r) + len(staged_d)
            state = dict(state)
            state["entities"] = staged_e
            state["relationships"] = staged_r
            state["delete_entity_ids"] = staged_d
            state["mutation_count"] = mutation_count
            _save_tx_state(client, state)
            envelope = {
                "contract_version": "kg-service-contract/v1",
                "status": "success",
                "operation": "write",
                "target": target.to_json_dict(),
                "result": {
                    "transaction_id": str(tx_id),
                    "state": "open",
                    "mutation_count": mutation_count,
                    "staged": True,
                },
                "error": None,
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            }
            return envelope, EXIT_OK
        # Fall through to in-process service staging when no durable state.
    result = client.write(target, idempotency_key=key, params=params)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_query(
    client,
    kwargs: Mapping[str, Any],
    *,
    fmt: str,
    stream_out: TextIO = sys.stdout,
) -> Tuple[Optional[Dict[str, Any]], int]:
    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    params = _merge_params(kwargs)
    language = (
        kwargs.get("language")
        or kwargs.get("query_language")
        or kwargs.get("query-language")
        or params.get("language")
        or "scan"
    )
    text = (
        kwargs.get("cypher")
        or kwargs.get("query")
        or kwargs.get("text")
        or params.get("text")
        or params.get("query")
        or ""
    )
    params["language"] = language
    if text:
        params["text"] = text
        params["query"] = text
    qparams = kwargs.get("query_params") or kwargs.get("query-params")
    if qparams is not None:
        loaded = _json_loads(qparams, what="--query-params")
        if not isinstance(loaded, Mapping):
            raise ValueError("--query-params must be a JSON object")
        params["params"] = dict(loaded)
    max_rows = kwargs.get("max_rows") or kwargs.get("max-rows") or kwargs.get("limit")
    budgets: Optional[Dict[str, Any]] = None
    if max_rows is not None:
        params["max_rows"] = int(max_rows)
        budgets = {"max_rows": int(max_rows)}

    do_stream = bool(kwargs.get("stream") or kwargs.get("streaming"))
    page_size = int(kwargs.get("page_size") or kwargs.get("page-size") or 100)

    if do_stream:
        pages = list(
            client.stream_query(
                target,
                params=params,
                budgets=budgets,
                page_size=page_size,
            )
        )
        if fmt == "json":
            for page in pages:
                _emit_ndjson(page.to_json_dict(), stream=stream_out)
            # Summary envelope for exit-code consumers (also last NDJSON if empty).
            if not pages:
                _emit_ndjson(
                    {
                        "status": "success",
                        "operation": "query",
                        "result": {"row_count": 0, "pages": 0},
                    },
                    stream=stream_out,
                )
            return None, EXIT_OK
        # table streaming: print each page
        total = 0
        for page in pages:
            total += page.row_count
            stream_out.write(
                f"# page {page.page_index} offset={page.offset} "
                f"rows={page.row_count} exhausted={page.exhausted}\n"
            )
            if page.columns:
                stream_out.write(" | ".join(str(c) for c in page.columns) + "\n")
            for row in page.rows:
                if isinstance(row, (list, tuple)):
                    stream_out.write(" | ".join(str(c) for c in row) + "\n")
                else:
                    stream_out.write(str(row) + "\n")
        stream_out.write(f"# total_rows: {total}\n")
        stream_out.flush()
        return None, EXIT_OK

    result = client.query(target, params=params, budgets=budgets)
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_branch(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(kwargs, require_graph=True)
    if target.branch is None:
        branch_name = kwargs.get("name") or kwargs.get("new_branch") or kwargs.get(
            "new-branch"
        )
        if not branch_name:
            raise ValueError("--branch (or branch in --target) is required")
        target = target.with_branch(str(branch_name))
    params = _merge_params(kwargs)
    for src, dst in (
        ("from_revision", "from_revision"),
        ("from-revision", "from_revision"),
        ("from_branch", "from_branch"),
        ("from-branch", "from_branch"),
        ("revision", "from_revision"),
    ):
        if src in kwargs and dst not in params:
            params[dst] = kwargs[src]
    key = _idempotency_key(kwargs, required=False)
    result = client.branch(
        target, params=params or None, idempotency_key=key
    )
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_delete(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    target = resolve_target(kwargs, require_graph=True)
    params = _merge_params(kwargs)
    if kwargs.get("reason"):
        params["reason"] = kwargs["reason"]
    key = _idempotency_key(kwargs, required=False)
    result = client.delete(
        target, params=params or None, idempotency_key=key
    )
    return _lifecycle_to_dict(result), _exit_for_result(result)


def cmd_transaction(
    client,
    kwargs: Mapping[str, Any],
    *,
    action: Optional[str] = None,
    stdin: TextIO = sys.stdin,
) -> Tuple[Dict[str, Any], int]:
    """Handle transaction begin|commit|rollback (durable across CLI processes).

    Staged mutations are persisted under the payload store so independent
    process invocations can begin → write → commit without sharing memory.
    """
    act = action or kwargs.get("action") or kwargs.get("subcommand")
    if not act:
        raise ValueError(
            "transaction requires action: begin|commit|rollback "
            "(e.g. graph transaction begin …)"
        )
    act = str(act).lower().replace("_", "-")
    aliases = {
        "begin": "begin",
        "begin-tx": "begin",
        "tx-begin": "begin",
        "start": "begin",
        "commit": "commit",
        "commit-tx": "commit",
        "tx-commit": "commit",
        "rollback": "rollback",
        "rollback-tx": "rollback",
        "tx-rollback": "rollback",
        "abort": "rollback",
        "run": "run",
    }
    if act not in aliases:
        raise ValueError(
            f"unknown transaction action {act!r}; use begin|commit|rollback|run"
        )
    act = aliases[act]

    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    branch = target.branch or DEFAULT_BRANCH
    if target.branch is None:
        target = target.with_branch(branch)
    params = _merge_params(kwargs)
    tx_id = (
        kwargs.get("tx_id")
        or kwargs.get("tx-id")
        or kwargs.get("transaction_id")
        or kwargs.get("transaction-id")
        or params.get("transaction_id")
    )
    if tx_id:
        params["transaction_id"] = str(tx_id)

    def _success(operation: str, result: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        return (
            {
                "contract_version": "kg-service-contract/v1",
                "status": "success",
                "operation": operation,
                "target": target.to_json_dict(),
                "result": result,
                "error": None,
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            },
            EXIT_OK,
        )

    def _error(
        operation: str, code: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], int]:
        return (
            {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": operation,
                "target": target.to_json_dict(),
                "result": None,
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": code in {"CONFLICT", "FENCED", "UNAVAILABLE", "BUDGET_EXCEEDED"},
                    "details": details or {},
                    "cause_code": None,
                },
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            },
            EXIT_ERROR,
        )

    if act == "begin":
        opened = client.open_graph(target)
        if not opened.ok:
            return _lifecycle_to_dict(opened), EXIT_ERROR
        base_revision = (opened.result or {}).get("revision")
        tx_id = str(params.get("transaction_id") or f"tx-{uuid.uuid4().hex}")
        if _load_tx_state(client, tx_id) is not None:
            return _error(
                "begin_tx",
                "ALREADY_EXISTS",
                "transaction_id already in use",
                {"transaction_id": tx_id},
            )
        state = {
            "transaction_id": tx_id,
            "tenant": target.tenant,
            "graph_id": target.graph_id,
            "branch": branch,
            "base_revision": base_revision,
            "state": "open",
            "entities": [],
            "relationships": [],
            "delete_entity_ids": [],
            "mutation_count": 0,
            "created_at": None,
        }
        _save_tx_state(client, state)
        # Also open an in-process service tx when possible (same-process follow-ups).
        try:
            client.begin_tx(
                target,
                params={"transaction_id": tx_id, "acquire_lease": False},
                idempotency_key=_idempotency_key(kwargs, required=False),
            )
        except Exception:
            pass
        return _success(
            "begin_tx",
            {
                "transaction_id": tx_id,
                "state": "open",
                "base_revision": base_revision,
                "branch": branch,
                "durable": True,
            },
        )

    if act == "commit":
        if not params.get("transaction_id"):
            raise ValueError("--tx-id is required for transaction commit")
        tx_id = str(params["transaction_id"])
        key = _idempotency_key(kwargs, required=True)
        state = _load_tx_state(client, tx_id)
        if state is None:
            # Fall back to in-process service transaction.
            result = client.commit_tx(
                target, idempotency_key=key, params=params
            )
            return _lifecycle_to_dict(result), _exit_for_result(result)
        if state.get("state") != "open":
            return _error(
                "commit_tx",
                "INVALID_REQUEST",
                f"transaction is not open (state={state.get('state')})",
                {"transaction_id": tx_id},
            )
        # Conflict if branch head moved since begin.
        opened = client.open_graph(target)
        if not opened.ok:
            return _lifecycle_to_dict(opened), EXIT_ERROR
        current_rev = (opened.result or {}).get("revision")
        base_revision = state.get("base_revision")
        if base_revision and current_rev and current_rev != base_revision:
            return _error(
                "commit_tx",
                "CONFLICT",
                "branch head moved since begin_tx",
                {
                    "expected_revision": base_revision,
                    "current_revision": current_rev,
                    "transaction_id": tx_id,
                },
            )
        write_params: Dict[str, Any] = {
            "entities": list(state.get("entities") or []),
            "relationships": list(state.get("relationships") or []),
        }
        if state.get("delete_entity_ids"):
            write_params["delete_entity_ids"] = list(state["delete_entity_ids"])
        if not write_params["entities"] and not write_params["relationships"] and not write_params.get("delete_entity_ids"):
            write_params["force_empty"] = True
        result = client.write(target, idempotency_key=key, params=write_params)
        if result.ok:
            _delete_tx_state(client, tx_id)
            envelope = _lifecycle_to_dict(result)
            envelope = dict(envelope)
            envelope["operation"] = "commit_tx"
            if isinstance(envelope.get("result"), dict):
                envelope["result"] = dict(envelope["result"])
                envelope["result"]["transaction_id"] = tx_id
                envelope["result"]["state"] = "committed"
            return envelope, EXIT_OK
        return _lifecycle_to_dict(result), EXIT_ERROR

    if act == "rollback":
        if not params.get("transaction_id"):
            raise ValueError("--tx-id is required for transaction rollback")
        tx_id = str(params["transaction_id"])
        state = _load_tx_state(client, tx_id)
        if state is not None:
            _delete_tx_state(client, tx_id)
            return _success(
                "rollback_tx",
                {
                    "transaction_id": tx_id,
                    "state": "rolled_back",
                    "durable": True,
                },
            )
        result = client.rollback_tx(target, params=params)
        return _lifecycle_to_dict(result), _exit_for_result(result)

    # act == "run": begin + stage mutations + commit in one process
    mutations = _collect_mutations(kwargs, stdin)
    key = _idempotency_key(kwargs, required=True)
    begin_env, begin_code = cmd_transaction(
        client,
        {**dict(kwargs), "action": "begin"},
        action="begin",
        stdin=stdin,
    )
    if begin_code != EXIT_OK:
        return begin_env, begin_code
    tx_id = str(begin_env["result"]["transaction_id"])
    state = _load_tx_state(client, tx_id)
    if state is None:
        return _error(
            "begin_tx",
            "INTERNAL",
            "failed to persist transaction state after begin",
            {"transaction_id": tx_id},
        )
    state = dict(state)
    state["entities"] = list(mutations.get("entities") or [])
    state["relationships"] = list(mutations.get("relationships") or [])
    state["delete_entity_ids"] = list(mutations.get("delete_entity_ids") or [])
    state["mutation_count"] = (
        len(state["entities"])
        + len(state["relationships"])
        + len(state["delete_entity_ids"])
    )
    _save_tx_state(client, state)
    return cmd_transaction(
        client,
        {
            **dict(kwargs),
            "action": "commit",
            "tx_id": tx_id,
            "idempotency_key": key,
        },
        action="commit",
        stdin=stdin,
    )


def cmd_import(
    client, kwargs: Mapping[str, Any], *, stdin: TextIO = sys.stdin
) -> Tuple[Dict[str, Any], int]:
    """Import entities/relationships via write (optionally create first)."""
    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    params = _collect_mutations(kwargs, stdin)
    if not params.get("entities") and not params.get("relationships"):
        raise ValueError(
            "import requires entities and/or relationships "
            "(--file/--stdin/--entities/--relationships)"
        )
    key = _idempotency_key(kwargs, required=False) or f"cli-import-{uuid.uuid4().hex}"

    create_if_missing = True
    if kwargs.get("no_create") or kwargs.get("no-create"):
        create_if_missing = False

    warnings: List[str] = []
    if create_if_missing:
        desc = client.describe(target)
        if not desc.ok:
            create_params: Dict[str, Any] = {}
            if target.storage_profile:
                create_params["storage_profile"] = target.storage_profile
            created = client.create(
                target,
                idempotency_key=f"{key}-create",
                params=create_params or None,
            )
            if not created.ok:
                return _lifecycle_to_dict(created), EXIT_ERROR
            warnings.append("graph created during import")

    result = client.write(target, idempotency_key=key, params=params)
    envelope = _lifecycle_to_dict(result)
    if warnings and envelope.get("status") == "success":
        existing = list(envelope.get("warnings") or [])
        existing.extend(warnings)
        envelope["warnings"] = existing
    # Annotate surface operation for consumers.
    if envelope.get("operation") == "write":
        envelope = dict(envelope)
        envelope["surface_operation"] = "import"
    return envelope, _exit_for_result(result)


def cmd_export(
    client,
    kwargs: Mapping[str, Any],
    *,
    fmt: str,
    stream_out: TextIO = sys.stdout,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """Export revision snapshot payload as JSON."""
    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    opened = client.open_graph(target)
    if not opened.ok:
        return _lifecycle_to_dict(opened), EXIT_ERROR

    # Use query scan for entities; relationships via service storage through
    # a second scan-like path — open payload already has counts; load via query
    # language "scan" for entities then export relationships from describe+storage.
    # Prefer full snapshot via storage when available on the client service.
    rev = opened.result["revision"] if opened.result else None
    snap_payload: Dict[str, Any]
    svc = client.service
    snap = svc.storage.get_snapshot(target.tenant, target.graph_id, rev)  # type: ignore[attr-defined]
    if snap is not None:
        snap_payload = {
            "tenant": snap.tenant,
            "graph_id": snap.graph_id,
            "revision": snap.revision,
            "parent_revision": snap.parent_revision,
            "entities": list(snap.entities),
            "relationships": list(snap.relationships),
            "metadata": dict(snap.metadata),
            "uri": f"kg://{snap.tenant}/{snap.graph_id}/revisions/{snap.revision}",
            "checksum": _checksum(snap.to_json_dict()),
            "entity_count": len(snap.entities),
            "relationship_count": len(snap.relationships),
        }
    else:
        q = client.query(target, params={"language": "scan"})
        if not q.ok:
            return _lifecycle_to_dict(q), EXIT_ERROR
        rows = (q.result or {}).get("rows") or []
        entities = []
        for row in rows:
            if isinstance(row, (list, tuple)) and len(row) >= 3:
                entities.append(
                    {
                        "id": row[0],
                        "type": row[1],
                        "name": row[2],
                        "properties": row[3] if len(row) > 3 else {},
                    }
                )
            elif isinstance(row, Mapping):
                entities.append(dict(row))
        snap_payload = {
            "tenant": target.tenant,
            "graph_id": target.graph_id,
            "revision": rev,
            "entities": entities,
            "relationships": [],
            "uri": (opened.result or {}).get("uri"),
            "entity_count": len(entities),
            "relationship_count": 0,
        }

    envelope: Dict[str, Any] = {
        "contract_version": "kg-service-contract/v1",
        "status": "success",
        "operation": "export",
        "target": opened.target.to_json_dict() if opened.target else None,
        "result": snap_payload,
        "error": None,
        "warnings": [],
        "request_id": opened.request_id,
        "authorization_receipt_ref": opened.authorization_receipt_ref,
    }

    out_path = kwargs.get("output") or kwargs.get("out") or kwargs.get("file")
    if out_path and out_path not in {"-", "/dev/stdout"}:
        Path(str(out_path)).write_text(
            json.dumps(snap_payload, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        if fmt == "json":
            _emit_json(
                {
                    **envelope,
                    "result": {
                        "path": str(out_path),
                        "revision": rev,
                        "entity_count": snap_payload.get("entity_count"),
                        "relationship_count": snap_payload.get("relationship_count"),
                        "checksum": snap_payload.get("checksum"),
                    },
                },
                stream=stream_out,
            )
            return None, EXIT_OK
        stream_out.write(
            f"status: success\noperation: export\npath: {out_path}\n"
            f"revision: {rev}\nentity_count: {snap_payload.get('entity_count')}\n"
            f"relationship_count: {snap_payload.get('relationship_count')}\n"
        )
        stream_out.flush()
        return None, EXIT_OK

    if fmt == "json":
        _emit_json(envelope, stream=stream_out)
        return None, EXIT_OK
    stream_out.write(_render_table_lifecycle(envelope))
    stream_out.flush()
    return None, EXIT_OK


def cmd_verify(client, kwargs: Mapping[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Verify graph snapshot presence, counts, and checksum consistency."""
    from ipfs_datasets_py.knowledge_graphs import GraphTarget

    target = resolve_target(
        kwargs, require_graph=True, default_branch=DEFAULT_BRANCH
    )
    opened = client.open_graph(target)
    if not opened.ok:
        return _lifecycle_to_dict(opened), EXIT_ERROR

    rev = opened.result["revision"] if opened.result else None
    # Prefer branch-scoped describe for head comparison.
    describe_target = GraphTarget(
        tenant=target.tenant,
        graph_id=target.graph_id,
        branch=target.branch or DEFAULT_BRANCH if target.revision is None else DEFAULT_BRANCH,
        revision=None,
        storage_profile=target.storage_profile,
    )
    described = client.describe(describe_target)

    snap = client.service.storage.get_snapshot(  # type: ignore[attr-defined]
        target.tenant, target.graph_id, rev
    )
    checks: Dict[str, Any] = {
        "revision_present": rev is not None,
        "snapshot_present": snap is not None,
        "revision": rev,
        "entity_count": len(snap.entities) if snap else None,
        "relationship_count": len(snap.relationships) if snap else None,
        "open_entity_count": (opened.result or {}).get("entity_count"),
        "open_relationship_count": (opened.result or {}).get("relationship_count"),
    }
    ok = True
    failures: List[str] = []
    if snap is None:
        ok = False
        failures.append("snapshot missing from storage")
    else:
        checksum = _checksum(snap.to_json_dict())
        checks["checksum"] = checksum
        open_ec = (opened.result or {}).get("entity_count")
        open_rc = (opened.result or {}).get("relationship_count")
        if open_ec is not None and open_ec != len(snap.entities):
            ok = False
            failures.append("entity_count mismatch between open and snapshot")
        if open_rc is not None and open_rc != len(snap.relationships):
            ok = False
            failures.append("relationship_count mismatch between open and snapshot")
        # Re-hash must be stable.
        if _checksum(snap.to_json_dict()) != checksum:
            ok = False
            failures.append("checksum not stable under recompute")

    # Optional expected checksum from CLI
    expected = kwargs.get("checksum") or kwargs.get("expected_checksum")
    if expected and checks.get("checksum") and str(expected) != checks["checksum"]:
        ok = False
        failures.append("checksum does not match --checksum")

    if described.ok and described.result and rev:
        head = described.result.get("head_revision")
        checks["head_revision"] = head
        if target.revision is None and head and head != rev:
            # open on branch should resolve to head
            ok = False
            failures.append(
                f"opened revision {rev} differs from head_revision {head}"
            )

    checks["ok"] = ok
    checks["failures"] = failures

    envelope: Dict[str, Any] = {
        "contract_version": "kg-service-contract/v1",
        "status": "success" if ok else "error",
        "operation": "verify",
        "target": opened.target.to_json_dict() if opened.target else None,
        "result": checks if ok else None,
        "error": None
        if ok
        else {
            "code": "CONFLICT" if failures else "INTERNAL",
            "message": "; ".join(failures) or "verification failed",
            "retryable": False,
            "details": checks,
            "cause_code": None,
        },
        "warnings": [],
        "request_id": opened.request_id,
        "authorization_receipt_ref": opened.authorization_receipt_ref,
    }
    return envelope, EXIT_OK if ok else EXIT_ERROR


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def parse_graph_args(args_list: Sequence[str]) -> Dict[str, Any]:
    """Parse ``--key value`` / ``--flag`` style args into a dict.

    Values that look like JSON are decoded. Unknown positional tokens after
    the subcommand are ignored (except transaction action).
    """
    kwargs: Dict[str, Any] = {}
    positionals: List[str] = []
    i = 0
    items = list(args_list)
    while i < len(items):
        arg = items[i]
        if arg == "--":
            positionals.extend(items[i + 1 :])
            break
        if arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(items) and not items[i + 1].startswith("--"):
                value: Any = items[i + 1]
                # Prefer raw string; decode JSON only for known JSON-ish keys
                # or when value clearly looks like JSON.
                if key.replace("-", "_") in {
                    "params",
                    "entities",
                    "relationships",
                    "delete_entity_ids",
                    "metadata",
                    "query_params",
                    "budgets",
                } or (
                    isinstance(value, str)
                    and value[:1] in "[{{\""
                    and value[-1:] in "]}\""
                ):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                # Normalize hyphens to both forms for lookup convenience.
                kwargs[key] = value
                kwargs[key.replace("-", "_")] = value
                i += 2
            else:
                kwargs[key] = True
                kwargs[key.replace("-", "_")] = True
                i += 1
        else:
            positionals.append(arg)
            i += 1
    if positionals:
        kwargs["_positionals"] = positionals
        # First positional often is transaction action.
        if "action" not in kwargs:
            kwargs["action"] = positionals[0]
    return kwargs


def resolve_output_format(
    kwargs: Mapping[str, Any], *, json_output: bool
) -> str:
    if json_output:
        return "json"
    fmt = kwargs.get("format") or kwargs.get("output_format") or kwargs.get(
        "output-format"
    )
    if fmt is None:
        return "table"
    fmt = str(fmt).lower()
    if fmt in {"json", "table", "pretty", "text"}:
        return "json" if fmt == "json" else "table"
    raise ValueError(f"unsupported --format {fmt!r}; use json|table")


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def handle_graph_command(
    args: Sequence[str],
    *,
    json_output: bool = False,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Dispatch ``graph <subcommand> …`` and return a process exit code.

    ``args`` is the full argv slice starting with ``\"graph\"`` (or just the
    subcommand tokens if the caller already stripped the top-level command).
    """
    tokens = list(args)
    if tokens and tokens[0] == "graph":
        tokens = tokens[1:]

    if not tokens or tokens[0] in {"-h", "--help", "help"}:
        stdout.write(HELP_TEXT)
        if not HELP_TEXT.endswith("\n"):
            stdout.write("\n")
        stdout.flush()
        return EXIT_OK

    subcommand = tokens[0]
    rest = tokens[1:]

    # Normalize aliases to canonical names.
    alias_map = {
        "tx-begin": ("transaction", "begin"),
        "tx-commit": ("transaction", "commit"),
        "tx-rollback": ("transaction", "rollback"),
        "begin_tx": ("transaction", "begin"),
        "commit_tx": ("transaction", "commit"),
        "rollback_tx": ("transaction", "rollback"),
        "begin-tx": ("transaction", "begin"),
        "commit-tx": ("transaction", "commit"),
        "rollback-tx": ("transaction", "rollback"),
    }
    forced_action: Optional[str] = None
    if subcommand in alias_map:
        subcommand, forced_action = alias_map[subcommand]

    try:
        kwargs = parse_graph_args(rest)
        if forced_action:
            kwargs["action"] = forced_action
        fmt = resolve_output_format(kwargs, json_output=json_output)
    except ValueError as exc:
        emit_usage_error(str(exc), stream=stderr)
        return EXIT_USAGE

    if subcommand not in GRAPH_SUBCOMMANDS and subcommand not in {
        "create",
        "list",
        "describe",
        "write",
        "query",
        "transaction",
        "branch",
        "delete",
        "import",
        "export",
        "verify",
        "open",
    }:
        emit_usage_error(
            f"unknown graph subcommand: {subcommand}",
            stream=stderr,
        )
        stderr.write(
            "Available: create list describe write query transaction "
            "branch delete import export verify open\n"
        )
        return EXIT_USAGE

    try:
        from ipfs_datasets_py.knowledge_graphs import Client  # noqa: F401
        from ipfs_datasets_py.knowledge_graphs.service import (  # noqa: F401
            GraphTargetError,
        )
    except ImportError as exc:
        stderr.write(f"Error: knowledge graph module not available: {exc}\n")
        stderr.write("Try: pip install -e . to install all dependencies\n")
        return EXIT_UNAVAILABLE

    try:
        catalog_path, storage_path = resolve_catalog_store(kwargs)
    except ValueError as exc:
        emit_usage_error(str(exc), stream=stderr)
        return EXIT_USAGE

    try:
        client = _open_client(catalog_path, storage_path)
    except Exception as exc:
        stderr.write(f"Error: failed to open GraphService catalog: {exc}\n")
        return EXIT_UNAVAILABLE

    try:
        envelope: Optional[Dict[str, Any]]
        code: int

        if subcommand == "create":
            envelope, code = cmd_create(client, kwargs)
        elif subcommand == "list":
            envelope, code = cmd_list(client, kwargs)
        elif subcommand == "describe":
            envelope, code = cmd_describe(client, kwargs)
        elif subcommand == "open":
            envelope, code = cmd_open(client, kwargs)
        elif subcommand == "write":
            envelope, code = cmd_write(client, kwargs, stdin=stdin)
        elif subcommand == "query":
            envelope, code = cmd_query(
                client, kwargs, fmt=fmt, stream_out=stdout
            )
        elif subcommand == "transaction":
            envelope, code = cmd_transaction(client, kwargs, stdin=stdin)
        elif subcommand == "branch":
            envelope, code = cmd_branch(client, kwargs)
        elif subcommand == "delete":
            envelope, code = cmd_delete(client, kwargs)
        elif subcommand == "import":
            envelope, code = cmd_import(client, kwargs, stdin=stdin)
        elif subcommand == "export":
            envelope, code = cmd_export(
                client, kwargs, fmt=fmt, stream_out=stdout
            )
        elif subcommand == "verify":
            envelope, code = cmd_verify(client, kwargs)
        else:
            emit_usage_error(
                f"unknown graph subcommand: {subcommand}", stream=stderr
            )
            return EXIT_USAGE

        if envelope is not None:
            emit_lifecycle_result(envelope, fmt=fmt, stream=stdout)
        return code
    except ValueError as exc:
        emit_usage_error(str(exc), stream=stderr)
        return EXIT_USAGE
    except Exception as exc:
        # Map GraphTargetError-like failures to usage/error with typed shape.
        from ipfs_datasets_py.knowledge_graphs.service import GraphTargetError

        if isinstance(exc, GraphTargetError):
            envelope = {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": subcommand,
                "target": None,
                "result": None,
                "error": {
                    "code": "INVALID_TARGET",
                    "message": str(exc),
                    "retryable": False,
                    "details": {"target_code": getattr(exc, "code", None)},
                    "cause_code": getattr(exc, "code", None),
                },
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            }
            emit_lifecycle_result(envelope, fmt=fmt, stream=stdout)
            return EXIT_ERROR
        stderr.write(f"Error executing graph command: {exc}\n")
        return EXIT_UNAVAILABLE
    finally:
        try:
            client.close()
        except Exception:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone ``python -m ipfs_datasets_py.ipfs_datasets_cli graph …``."""
    argv_list = list(sys.argv[1:] if argv is None else argv)
    json_output = False
    if "--json" in argv_list:
        json_output = True
        argv_list = [a for a in argv_list if a != "--json"]
    if argv_list and argv_list[0] == "graph":
        return handle_graph_command(argv_list, json_output=json_output)
    # Allow invoking without the leading ``graph`` token when run as module.
    if argv_list and argv_list[0] in GRAPH_SUBCOMMANDS | {
        "create",
        "list",
        "describe",
        "write",
        "query",
        "transaction",
        "branch",
        "delete",
        "import",
        "export",
        "verify",
        "open",
    }:
        return handle_graph_command(
            ["graph", *argv_list], json_output=json_output
        )
    sys.stdout.write(HELP_TEXT)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
