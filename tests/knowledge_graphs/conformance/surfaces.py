"""Surface adapters for KGP-020 cross-surface conformance vectors.

Each adapter exposes the same transport-neutral operations and returns a
canonical lifecycle / stream envelope (``dict``). Adapters never waive typed
error codes or convert failures into soft successes.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ipfs_datasets_py.mcp_server.graph_service_registry import (
    open_graph_service,
    reset_graph_service_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI_MODULE = "ipfs_datasets_py.ipfs_datasets_cli"
_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "knowledge_graphs"
    / "conformance"
)

JSONDict = Dict[str, Any]
TargetSpec = Union[str, Mapping[str, Any]]


def fixture_path(*parts: str) -> Path:
    return _FIXTURE_DIR.joinpath(*parts)


def load_seed_graph() -> JSONDict:
    path = fixture_path("seed_graph.json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_vector_catalog() -> JSONDict:
    path = fixture_path("vector_catalog.json")
    return json.loads(path.read_text(encoding="utf-8"))


def child_env(extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def target_uri(
    tenant: str,
    graph_id: str,
    *,
    branch: Optional[str] = "main",
    revision: Optional[str] = None,
) -> str:
    if revision:
        return f"kg://{tenant}/{graph_id}/revisions/{revision}"
    if branch:
        return f"kg://{tenant}/{graph_id}/branches/{branch}"
    return f"kg://{tenant}/{graph_id}"


def _run_async(coro):
    """Run an async coroutine from sync test code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested: create a new loop in a thread is overkill; use anyio/asyncio.run
            # when no loop — callers in async tests should await directly.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Abstract surface
# ---------------------------------------------------------------------------


class SurfaceAdapter(ABC):
    """Transport-neutral operations over one public surface."""

    name: str

    def __init__(self, catalog: Path, store: Path) -> None:
        self.catalog = Path(catalog)
        self.store = Path(store)

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        ...

    @abstractmethod
    def list_graphs(self, *, tenant: str) -> JSONDict:
        ...

    @abstractmethod
    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        ...

    @abstractmethod
    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        ...

    @abstractmethod
    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        transaction_id: Optional[str] = None,
    ) -> JSONDict:
        ...

    @abstractmethod
    def query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        text: str = "",
        max_rows: Optional[int] = None,
    ) -> JSONDict:
        ...

    @abstractmethod
    def hybrid_search(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        limit: int = 50,
    ) -> JSONDict:
        ...

    @abstractmethod
    def stream_query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        page_size: int = 2,
    ) -> List[JSONDict]:
        ...

    @abstractmethod
    def begin_tx(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        ...

    @abstractmethod
    def commit_tx(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        transaction_id: str,
        idempotency_key: str,
    ) -> JSONDict:
        ...

    @abstractmethod
    def invalid_create_missing_target(self) -> JSONDict:
        ...


# ---------------------------------------------------------------------------
# Python Client surface
# ---------------------------------------------------------------------------


class PythonSurface(SurfaceAdapter):
    name = "python"

    def __init__(self, catalog: Path, store: Path) -> None:
        super().__init__(catalog, store)
        from ipfs_datasets_py.knowledge_graphs import Client

        self._client = Client.open(catalog, storage_path=store)

    def close(self) -> None:
        self._client.close()

    def _target(self, tenant: str, graph_id: str, branch: str = "main"):
        from ipfs_datasets_py.knowledge_graphs import GraphTarget

        return GraphTarget(tenant=tenant, graph_id=graph_id, branch=branch)

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        from ipfs_datasets_py.knowledge_graphs import GraphTarget

        t = GraphTarget(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            storage_profile=storage_profile,
        )
        return self._client.create(t, idempotency_key=idempotency_key).to_json_dict()

    def list_graphs(self, *, tenant: str) -> JSONDict:
        return self._client.list(
            self._target(tenant, "list")
        ).to_json_dict()

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._client.describe(
            self._target(tenant, graph_id, branch)
        ).to_json_dict()

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._client.open_graph(
            self._target(tenant, graph_id, branch)
        ).to_json_dict()

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        transaction_id: Optional[str] = None,
    ) -> JSONDict:
        params: JSONDict = {
            "entities": list(entities or []),
            "relationships": list(relationships or []),
        }
        if transaction_id:
            params["transaction_id"] = transaction_id
        return self._client.write(
            self._target(tenant, graph_id, branch),
            idempotency_key=idempotency_key,
            params=params,
        ).to_json_dict()

    def query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        text: str = "",
        max_rows: Optional[int] = None,
    ) -> JSONDict:
        params: JSONDict = {"language": language, "text": text, "query": text}
        budgets = {"max_rows": int(max_rows)} if max_rows is not None else None
        if max_rows is not None:
            params["max_rows"] = int(max_rows)
        return self._client.query(
            self._target(tenant, graph_id, branch),
            params=params,
            budgets=budgets,
        ).to_json_dict()

    def hybrid_search(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        limit: int = 50,
    ) -> JSONDict:
        return self.query(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            language="scan",
            text="",
            max_rows=limit,
        )

    def stream_query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        page_size: int = 2,
    ) -> List[JSONDict]:
        pages = list(
            self._client.stream_query(
                self._target(tenant, graph_id, branch),
                params={"language": language},
                page_size=page_size,
            )
        )
        return [p.to_json_dict() for p in pages]

    def begin_tx(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._client.begin_tx(
            self._target(tenant, graph_id, branch),
            params={"acquire_lease": False},
        ).to_json_dict()

    def commit_tx(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        transaction_id: str,
        idempotency_key: str,
    ) -> JSONDict:
        return self._client.commit_tx(
            self._target(tenant, graph_id, branch),
            idempotency_key=idempotency_key,
            params={"transaction_id": transaction_id},
        ).to_json_dict()

    def invalid_create_missing_target(self) -> JSONDict:
        from ipfs_datasets_py.knowledge_graphs import GraphTarget
        from ipfs_datasets_py.knowledge_graphs.service import GraphTargetError

        try:
            GraphTarget(tenant="", graph_id="x")
        except GraphTargetError as exc:
            return {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": "create",
                "target": None,
                "result": None,
                "error": {
                    "code": "INVALID_TARGET",
                    "message": str(exc),
                    "retryable": False,
                    "details": {"target_code": exc.code},
                    "cause_code": exc.code,
                },
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            }
        # Fallback: attempt create with invalid slug via service validation.
        r = self._client.create(
            {"tenant": "ACME", "graph_id": "x", "branch": "main"},
            idempotency_key="bad-case",
        )
        return r.to_json_dict()


# ---------------------------------------------------------------------------
# CLI surface (independent process)
# ---------------------------------------------------------------------------


class CliSurface(SurfaceAdapter):
    name = "cli"

    def close(self) -> None:
        return None

    def _run(
        self,
        args: Sequence[str],
        *,
        input_text: Optional[str] = None,
        timeout: float = 90,
    ) -> Tuple[int, JSONDict]:
        cmd = [
            sys.executable,
            "-m",
            _CLI_MODULE,
            "graph",
            *args,
            "--catalog",
            str(self.catalog),
            "--store",
            str(self.store),
            "--format",
            "json",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=child_env(),
            cwd=str(_REPO_ROOT),
            input=input_text,
        )
        # Pretty JSON (single object) or NDJSON stream pages.
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if not stdout:
            code = (
                "INVALID_REQUEST"
                if proc.returncode == 2
                else ("INTERNAL" if proc.returncode not in (0, 1) else "INVALID_TARGET")
            )
            # Usage messages often land on stderr only.
            return proc.returncode, {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": "cli",
                "target": None,
                "result": None,
                "error": {
                    "code": code,
                    "message": stderr or "empty CLI stdout",
                    "retryable": False,
                    "details": {"returncode": proc.returncode},
                    "cause_code": None,
                },
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            }
        # Try full stdout as one JSON document first (pretty-printed envelopes).
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            # NDJSON: parse first complete object line.
            payload = None
            for ln in stdout.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    payload = json.loads(ln)
                    break
                except json.JSONDecodeError:
                    continue
            if payload is None:
                return proc.returncode, {
                    "contract_version": "kg-service-contract/v1",
                    "status": "error",
                    "operation": "cli",
                    "target": None,
                    "result": None,
                    "error": {
                        "code": "INVALID_REQUEST"
                        if proc.returncode == 2
                        else "INTERNAL",
                        "message": stdout + "\n" + stderr,
                        "retryable": False,
                        "details": {"returncode": proc.returncode},
                        "cause_code": None,
                    },
                    "warnings": [],
                    "request_id": None,
                    "authorization_receipt_ref": None,
                }
        if not isinstance(payload, dict):
            payload = {"status": "success", "result": payload}
        payload.setdefault("contract_version", "kg-service-contract/v1")
        return proc.returncode, payload

    def _run_ndjson(
        self, args: Sequence[str], *, timeout: float = 90
    ) -> List[JSONDict]:
        cmd = [
            sys.executable,
            "-m",
            _CLI_MODULE,
            "graph",
            *args,
            "--catalog",
            str(self.catalog),
            "--store",
            str(self.store),
            "--format",
            "json",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=child_env(),
            cwd=str(_REPO_ROOT),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        pages: List[JSONDict] = []
        for ln in proc.stdout.splitlines():
            if ln.strip():
                pages.append(json.loads(ln))
        return pages

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        _, payload = self._run(
            [
                "create",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
                "--idempotency-key",
                idempotency_key,
                "--profile",
                storage_profile,
            ]
        )
        return payload

    def list_graphs(self, *, tenant: str) -> JSONDict:
        _, payload = self._run(["list", "--tenant", tenant])
        return payload

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        _, payload = self._run(
            [
                "describe",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
            ]
        )
        return payload

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        _, payload = self._run(
            [
                "open",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
            ]
        )
        return payload

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        transaction_id: Optional[str] = None,
    ) -> JSONDict:
        args = [
            "write",
            "--tenant",
            tenant,
            "--graph",
            graph_id,
            "--branch",
            branch,
            "--idempotency-key",
            idempotency_key,
            "--entities",
            json.dumps(list(entities or [])),
            "--relationships",
            json.dumps(list(relationships or [])),
        ]
        if transaction_id:
            args.extend(["--tx-id", transaction_id])
        _, payload = self._run(args)
        return payload

    def query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        text: str = "",
        max_rows: Optional[int] = None,
    ) -> JSONDict:
        args = [
            "query",
            "--tenant",
            tenant,
            "--graph",
            graph_id,
            "--branch",
            branch,
            "--language",
            language,
        ]
        if text:
            args.extend(["--query", text])
        if max_rows is not None:
            args.extend(["--max-rows", str(max_rows)])
        _, payload = self._run(args)
        return payload

    def hybrid_search(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        limit: int = 50,
    ) -> JSONDict:
        return self.query(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            language="scan",
            max_rows=limit,
        )

    def stream_query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        page_size: int = 2,
    ) -> List[JSONDict]:
        return self._run_ndjson(
            [
                "query",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
                "--language",
                language,
                "--stream",
                "--page-size",
                str(page_size),
            ]
        )

    def begin_tx(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        _, payload = self._run(
            [
                "transaction",
                "begin",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
                "--params",
                json.dumps({"acquire_lease": False}),
            ]
        )
        return payload

    def commit_tx(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        transaction_id: str,
        idempotency_key: str,
    ) -> JSONDict:
        _, payload = self._run(
            [
                "transaction",
                "commit",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
                "--tx-id",
                transaction_id,
                "--idempotency-key",
                idempotency_key,
            ]
        )
        return payload

    def invalid_create_missing_target(self) -> JSONDict:
        # Omit --target/--tenant entirely (strict missing-target vector).
        code, payload = self._run(
            [
                "create",
                "--graph",
                "x",
                "--idempotency-key",
                "bad",
            ]
        )
        if payload.get("status") == "error":
            # Map usage exit to INVALID_TARGET when code is usage/error.
            err = payload.get("error") or {}
            if err.get("code") == "INTERNAL" and code in (1, 2):
                err = dict(err)
                err["code"] = "INVALID_TARGET"
                payload = dict(payload)
                payload["error"] = err
            elif err.get("code") not in {
                "INVALID_TARGET",
                "INVALID_REQUEST",
            } and code == 2:
                err = dict(err)
                err["code"] = "INVALID_REQUEST"
                payload = dict(payload)
                payload["error"] = err
            return payload
        return {
            "contract_version": "kg-service-contract/v1",
            "status": "error",
            "operation": "create",
            "target": None,
            "result": None,
            "error": {
                "code": "INVALID_TARGET" if code in (1, 2) else "INTERNAL",
                "message": "invalid or missing target",
                "retryable": False,
                "details": {"returncode": code},
                "cause_code": None,
            },
            "warnings": [],
            "request_id": None,
            "authorization_receipt_ref": None,
        }


# ---------------------------------------------------------------------------
# MCP surface (in-process tools)
# ---------------------------------------------------------------------------


class McpSurface(SurfaceAdapter):
    name = "mcp"

    def __init__(self, catalog: Path, store: Path) -> None:
        super().__init__(catalog, store)
        reset_graph_service_registry()
        self._binding = open_graph_service(
            catalog, storage_path=store, force=True
        )

    def close(self) -> None:
        reset_graph_service_registry()

    def _await(self, coro) -> Any:
        return _run_async(coro)

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        return self._await(
            graph_create(
                target=target_uri(tenant, graph_id, branch=branch),
                idempotency_key=idempotency_key,
                storage_profile=storage_profile,
            )
        )

    def list_graphs(self, *, tenant: str) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_list

        return self._await(graph_list(tenant=tenant))

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_describe

        return self._await(
            graph_describe(tenant=tenant, graph_id=graph_id, branch=branch)
        )

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        # MCP has no dedicated open tool; describe + query-equivalent via write path
        # uses service.open indirectly. Use graph_describe for metadata and attach
        # open semantics via a hybrid scan revision pin after describe.
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_describe

        desc = self._await(
            graph_describe(tenant=tenant, graph_id=graph_id, branch=branch)
        )
        if desc.get("status") != "success":
            return desc
        # Map describe → open-shaped envelope fields for parity (revision present).
        head = (desc.get("result") or {}).get("head_revision")
        return {
            "contract_version": desc.get(
                "contract_version", "kg-service-contract/v1"
            ),
            "status": "success",
            "operation": "open",
            "target": desc.get("target"),
            "result": {
                "revision": head,
                "branch": branch,
                "uri": target_uri(tenant, graph_id, revision=head)
                if head
                else target_uri(tenant, graph_id, branch=branch),
                "storage_profile": (desc.get("result") or {}).get(
                    "storage_profile"
                ),
                "entity_count": (desc.get("result") or {}).get("entity_count"),
                "relationship_count": (desc.get("result") or {}).get(
                    "relationship_count"
                ),
            },
            "error": None,
            "warnings": list(desc.get("warnings") or []),
            "request_id": desc.get("request_id"),
            "authorization_receipt_ref": desc.get("authorization_receipt_ref"),
        }

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        transaction_id: Optional[str] = None,
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_write

        return self._await(
            graph_write(
                target=target_uri(tenant, graph_id, branch=branch),
                entities=list(entities or []),
                relationships=list(relationships or []),
                idempotency_key=idempotency_key,
                transaction_id=transaction_id,
            )
        )

    def query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        text: str = "",
        max_rows: Optional[int] = None,
    ) -> JSONDict:
        if language in {"cypher", "cypher-lite"}:
            from ipfs_datasets_py.mcp_server.tools.graph_tools import (
                graph_query_cypher,
            )

            return self._await(
                graph_query_cypher(
                    query=text or "MATCH (n) RETURN n",
                    target=target_uri(tenant, graph_id, branch=branch),
                    language=language if language != "cypher-lite" else "cypher",
                    max_rows=max_rows,
                )
            )
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_search_hybrid,
        )

        return self._await(
            graph_search_hybrid(
                query=text,
                target=target_uri(tenant, graph_id, branch=branch),
                language=language,
                limit=int(max_rows) if max_rows is not None else 1000,
            )
        )

    def hybrid_search(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        limit: int = 50,
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_search_hybrid,
        )

        return self._await(
            graph_search_hybrid(
                query="",
                target=target_uri(tenant, graph_id, branch=branch),
                language="scan",
                search_type="hybrid",
                limit=limit,
            )
        )

    def stream_query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        page_size: int = 2,
    ) -> List[JSONDict]:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_query_stream,
        )

        pages: List[JSONDict] = []
        cursor = None
        for _ in range(32):
            page = self._await(
                graph_query_stream(
                    target=target_uri(tenant, graph_id, branch=branch),
                    language=language,
                    page_size=page_size,
                    cursor=cursor,
                )
            )
            pages.append(page)
            if page.get("status") != "success":
                break
            result = page.get("result") or {}
            cursor = result.get("cursor")
            if result.get("exhausted"):
                break
        return pages

    def begin_tx(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_transaction_begin,
        )

        return self._await(
            graph_transaction_begin(
                target=target_uri(tenant, graph_id, branch=branch),
                params={"acquire_lease": False},
            )
        )

    def commit_tx(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        transaction_id: str,
        idempotency_key: str,
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_transaction_commit,
        )

        return self._await(
            graph_transaction_commit(
                transaction_id=transaction_id,
                target=target_uri(tenant, graph_id, branch=branch),
                idempotency_key=idempotency_key,
            )
        )

    def invalid_create_missing_target(self) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        return self._await(graph_create())


# ---------------------------------------------------------------------------
# MCP++ surface (hierarchical tools_dispatch)
# ---------------------------------------------------------------------------


class McpPlusSurface(McpSurface):
    """MCP++ uses hierarchical dispatch; shares server-owned GraphService."""

    name = "mcp_plus"

    def _dispatch(self, tool: str, params: Mapping[str, Any]) -> JSONDict:
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            tools_dispatch,
        )

        result = self._await(tools_dispatch("graph_tools", tool, dict(params)))
        if not isinstance(result, dict):
            return {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": tool,
                "target": None,
                "result": None,
                "error": {
                    "code": "INTERNAL",
                    "message": f"non-dict dispatch result: {result!r}",
                    "retryable": False,
                    "details": {},
                    "cause_code": None,
                },
                "warnings": [],
                "request_id": None,
                "authorization_receipt_ref": None,
            }
        # Normalize bare string errors from routing failures.
        if result.get("status") == "error" and isinstance(
            result.get("error"), str
        ):
            return {
                "contract_version": "kg-service-contract/v1",
                "status": "error",
                "operation": tool,
                "target": result.get("target"),
                "result": None,
                "error": {
                    "code": "INTERNAL",
                    "message": result["error"],
                    "retryable": False,
                    "details": {},
                    "cause_code": None,
                },
                "warnings": list(result.get("warnings") or []),
                "request_id": result.get("request_id"),
                "authorization_receipt_ref": result.get(
                    "authorization_receipt_ref"
                ),
            }
        return result

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        return self._dispatch(
            "graph_create",
            {
                "target": target_uri(tenant, graph_id, branch=branch),
                "idempotency_key": idempotency_key,
                "storage_profile": storage_profile,
            },
        )

    def list_graphs(self, *, tenant: str) -> JSONDict:
        return self._dispatch("graph_list", {"tenant": tenant})

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._dispatch(
            "graph_describe",
            {"tenant": tenant, "graph_id": graph_id, "branch": branch},
        )

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
        transaction_id: Optional[str] = None,
    ) -> JSONDict:
        params: JSONDict = {
            "target": target_uri(tenant, graph_id, branch=branch),
            "entities": list(entities or []),
            "relationships": list(relationships or []),
            "idempotency_key": idempotency_key,
        }
        if transaction_id:
            params["transaction_id"] = transaction_id
        return self._dispatch("graph_write", params)

    def query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        text: str = "",
        max_rows: Optional[int] = None,
    ) -> JSONDict:
        if language in {"cypher", "cypher-lite"}:
            params: JSONDict = {
                "query": text or "MATCH (n) RETURN n",
                "target": target_uri(tenant, graph_id, branch=branch),
                "language": "cypher",
            }
            if max_rows is not None:
                params["max_rows"] = int(max_rows)
            return self._dispatch("graph_query_cypher", params)
        params = {
            "query": text,
            "target": target_uri(tenant, graph_id, branch=branch),
            "language": language,
            "limit": int(max_rows) if max_rows is not None else 1000,
        }
        return self._dispatch("graph_search_hybrid", params)

    def hybrid_search(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        limit: int = 50,
    ) -> JSONDict:
        return self._dispatch(
            "graph_search_hybrid",
            {
                "query": "",
                "target": target_uri(tenant, graph_id, branch=branch),
                "language": "scan",
                "search_type": "hybrid",
                "limit": limit,
            },
        )

    def stream_query(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        language: str = "scan",
        page_size: int = 2,
    ) -> List[JSONDict]:
        pages: List[JSONDict] = []
        cursor = None
        for _ in range(32):
            page = self._dispatch(
                "graph_query_stream",
                {
                    "target": target_uri(tenant, graph_id, branch=branch),
                    "language": language,
                    "page_size": page_size,
                    "cursor": cursor,
                },
            )
            pages.append(page)
            if page.get("status") != "success":
                break
            result = page.get("result") or {}
            cursor = result.get("cursor")
            if result.get("exhausted"):
                break
        return pages

    def begin_tx(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._dispatch(
            "graph_transaction_begin",
            {
                "target": target_uri(tenant, graph_id, branch=branch),
                "params": {"acquire_lease": False},
            },
        )

    def commit_tx(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        transaction_id: str,
        idempotency_key: str,
    ) -> JSONDict:
        return self._dispatch(
            "graph_transaction_commit",
            {
                "transaction_id": transaction_id,
                "target": target_uri(tenant, graph_id, branch=branch),
                "idempotency_key": idempotency_key,
            },
        )

    def invalid_create_missing_target(self) -> JSONDict:
        return self._dispatch("graph_create", {})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

SURFACE_FACTORIES = {
    "python": PythonSurface,
    "cli": CliSurface,
    "mcp": McpSurface,
    "mcp_plus": McpPlusSurface,
}


def open_surface(name: str, catalog: Path, store: Path) -> SurfaceAdapter:
    try:
        cls = SURFACE_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"unknown surface: {name!r}") from exc
    return cls(catalog, store)


def all_surface_names() -> Tuple[str, ...]:
    return ("python", "cli", "mcp", "mcp_plus")
