"""Load-surface adapters: Python / CLI / MCP / MCP++ (KGP-029).

Adapters share a small transport-neutral contract used by the harness for
create / write / open / query / close. Python is the fast path for CI; other
surfaces exercise the real public entry points when selected by a profile.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

JSONDict = Dict[str, Any]

SURFACE_NAMES: Tuple[str, ...] = ("python", "cli", "mcp", "mcp_plus")
STORAGE_PROFILES: Tuple[str, ...] = (
    "parquet",
    "ipfs_ipld",
    "ipfs_kit",
    "hybrid",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_MODULE = "ipfs_datasets_py.ipfs_datasets_cli"


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


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _error_envelope(
    operation: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: Optional[Mapping[str, Any]] = None,
) -> JSONDict:
    return {
        "contract_version": "kg-service-contract/v1",
        "status": "error",
        "operation": operation,
        "target": None,
        "result": None,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": dict(details or {}),
            "cause_code": None,
        },
        "warnings": [],
        "request_id": None,
        "authorization_receipt_ref": None,
    }


class LoadSurface(ABC):
    """Minimal surface for load harness operations."""

    name: str

    def __init__(self, catalog: Path, store: Path) -> None:
        self.catalog = Path(catalog)
        self.store = Path(store)

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict: ...

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
    ) -> JSONDict: ...

    @abstractmethod
    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict: ...

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
    ) -> JSONDict: ...

    @abstractmethod
    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict: ...


# ---------------------------------------------------------------------------
# Python Client surface
# ---------------------------------------------------------------------------


class PythonLoadSurface(LoadSurface):
    name = "python"

    def __init__(self, catalog: Path, store: Path) -> None:
        super().__init__(catalog, store)
        from ipfs_datasets_py.knowledge_graphs.client import Client

        self._client = Client.open(catalog, storage_path=store)

    def close(self) -> None:
        self._client.close()

    def _target(
        self,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        storage_profile: Optional[str] = None,
    ):
        from ipfs_datasets_py.knowledge_graphs.service import GraphTarget

        kwargs: JSONDict = {
            "tenant": tenant,
            "graph_id": graph_id,
            "branch": branch,
        }
        if storage_profile is not None:
            kwargs["storage_profile"] = storage_profile
        return GraphTarget(**kwargs)

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        t = self._target(tenant, graph_id, branch, storage_profile=storage_profile)
        return self._client.create(t, idempotency_key=idempotency_key).to_json_dict()

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> JSONDict:
        params: JSONDict = {
            "entities": list(entities or []),
            "relationships": list(relationships or []),
        }
        return self._client.write(
            self._target(tenant, graph_id, branch),
            idempotency_key=idempotency_key,
            params=params,
        ).to_json_dict()

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._client.open_graph(
            self._target(tenant, graph_id, branch)
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

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._client.describe(
            self._target(tenant, graph_id, branch)
        ).to_json_dict()


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class CliLoadSurface(LoadSurface):
    name = "cli"

    def close(self) -> None:
        return None

    def _run(
        self,
        args: Sequence[str],
        *,
        input_text: Optional[str] = None,
        timeout: float = 120,
    ) -> JSONDict:
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
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=child_env(),
                cwd=str(_REPO_ROOT),
                input=input_text,
            )
        except subprocess.TimeoutExpired as exc:
            return _error_envelope(
                "cli",
                "TIMEOUT",
                f"CLI timed out after {timeout}s",
                retryable=True,
                details={"args": list(args)},
            )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if not stdout:
            return _error_envelope(
                "cli",
                "INTERNAL" if proc.returncode not in (0, 1, 2) else "INVALID_REQUEST",
                stderr or "empty CLI stdout",
                details={"returncode": proc.returncode},
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
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
                return _error_envelope(
                    "cli",
                    "INTERNAL",
                    stdout + "\n" + stderr,
                    details={"returncode": proc.returncode},
                )
        if not isinstance(payload, dict):
            payload = {"status": "success", "result": payload}
        payload.setdefault("contract_version", "kg-service-contract/v1")
        return payload

    def create(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        storage_profile: str = "parquet",
    ) -> JSONDict:
        return self._run(
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

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> JSONDict:
        payload = {
            "entities": list(entities or []),
            "relationships": list(relationships or []),
        }
        return self._run(
            [
                "write",
                "--tenant",
                tenant,
                "--graph",
                graph_id,
                "--branch",
                branch,
                "--idempotency-key",
                idempotency_key,
            ],
            input_text=json.dumps(payload),
        )

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._run(
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
            args.extend(["--text", text])
        if max_rows is not None:
            args.extend(["--max-rows", str(int(max_rows))])
        return self._run(args)

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        return self._run(
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


# ---------------------------------------------------------------------------
# MCP / MCP++ surfaces
# ---------------------------------------------------------------------------


class McpLoadSurface(LoadSurface):
    name = "mcp"

    def __init__(self, catalog: Path, store: Path) -> None:
        super().__init__(catalog, store)
        from ipfs_datasets_py.mcp_server.graph_service_registry import (
            open_graph_service,
            reset_graph_service_registry,
        )

        reset_graph_service_registry()
        self._binding = open_graph_service(
            catalog, storage_path=store, force=True
        )

    def close(self) -> None:
        try:
            from ipfs_datasets_py.mcp_server.graph_service_registry import (
                reset_graph_service_registry,
            )

            reset_graph_service_registry()
        except Exception:
            pass

    def _await(self, coro: Any) -> Any:
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

    def write(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str = "main",
        idempotency_key: str,
        entities: Optional[Sequence[Mapping[str, Any]]] = None,
        relationships: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_write

        return self._await(
            graph_write(
                target=target_uri(tenant, graph_id, branch=branch),
                idempotency_key=idempotency_key,
                entities=list(entities or []),
                relationships=list(relationships or []),
            )
        )

    def open_graph(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_describe

        desc = self._await(
            graph_describe(tenant=tenant, graph_id=graph_id, branch=branch)
        )
        if desc.get("status") != "success":
            return desc
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
            },
            "error": None,
            "warnings": list(desc.get("warnings") or []),
            "request_id": desc.get("request_id"),
            "authorization_receipt_ref": desc.get("authorization_receipt_ref"),
        }

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
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_search_hybrid,
        )

        return self._await(
            graph_search_hybrid(
                query=text or "",
                target=target_uri(tenant, graph_id, branch=branch),
                language=language,
                limit=int(max_rows) if max_rows is not None else 1000,
            )
        )

    def describe(
        self, *, tenant: str, graph_id: str, branch: str = "main"
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_describe

        return self._await(
            graph_describe(tenant=tenant, graph_id=graph_id, branch=branch)
        )


class McpPlusLoadSurface(McpLoadSurface):
    """MCP++ surface — same tools with enhanced request metadata."""

    name = "mcp_plus"

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
                request_id=f"mcp-plus-{uuid.uuid4().hex[:12]}",
            )
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
    ) -> JSONDict:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_write

        return self._await(
            graph_write(
                target=target_uri(tenant, graph_id, branch=branch),
                idempotency_key=idempotency_key,
                entities=list(entities or []),
                relationships=list(relationships or []),
                request_id=f"mcp-plus-{uuid.uuid4().hex[:12]}",
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
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_search_hybrid,
        )

        return self._await(
            graph_search_hybrid(
                query=text or "",
                target=target_uri(tenant, graph_id, branch=branch),
                language=language,
                limit=int(max_rows) if max_rows is not None else 1000,
                request_id=f"mcp-plus-{uuid.uuid4().hex[:12]}",
            )
        )


SURFACE_FACTORIES = {
    "python": PythonLoadSurface,
    "cli": CliLoadSurface,
    "mcp": McpLoadSurface,
    "mcp_plus": McpPlusLoadSurface,
}


def open_load_surface(name: str, catalog: Path, store: Path) -> LoadSurface:
    key = name.strip().lower().replace("-", "_").replace("++", "_plus")
    if key == "mcpplusplus":
        key = "mcp_plus"
    try:
        cls = SURFACE_FACTORIES[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown surface {name!r}; expected one of {SURFACE_NAMES}"
        ) from exc
    return cls(catalog, store)


def envelope_ok(envelope: Mapping[str, Any]) -> bool:
    return str(envelope.get("status") or "").lower() == "success"


def envelope_conflict(envelope: Mapping[str, Any]) -> bool:
    err = envelope.get("error") or {}
    if not isinstance(err, Mapping):
        return False
    code = str(err.get("code") or "").upper()
    return "CONFLICT" in code or code in {
        "IDEMPOTENCY_CONFLICT",
        "REVISION_CONFLICT",
        "CAS_CONFLICT",
        "LEASE_FENCED",
    }


def estimate_payload_bytes(
    entities: Optional[Sequence[Mapping[str, Any]]] = None,
    relationships: Optional[Sequence[Mapping[str, Any]]] = None,
) -> int:
    payload = {
        "entities": list(entities or []),
        "relationships": list(relationships or []),
    }
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
