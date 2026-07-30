"""Shared bridge from MCP graph tools onto the server-owned GraphService.

Every public graph tool:

* requires an explicit :class:`GraphTarget` (URI or tenant/graph fields);
* returns a canonical JSON-safe lifecycle / stream envelope;
* resolves the process GraphService (never a fresh manager per call);
* declares MCP++ resource / effect / ability metadata.
"""

from __future__ import annotations

import json
import hashlib
import logging
import tempfile
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ipfs_datasets_py.knowledge_graphs.service import (
    CONTRACT_VERSION,
    GraphTarget,
    GraphTargetError,
    LifecycleResult,
    TypedError,
)
from ipfs_datasets_py.mcp_server.graph_service_registry import (
    ENV_CATALOG,
    ENV_STORE,
    get_graph_service_binding,
)

logger = logging.getLogger(__name__)

DEFAULT_BRANCH = "main"
LIST_WILDCARD_GRAPH = "list"

# Ability vocabulary (MCP++ / plan § MCP++ and UCAN)
ABILITY_LIST = "graph/list"
ABILITY_READ = "graph/read"
ABILITY_QUERY = "graph/query"
ABILITY_WRITE = "graph/write"
ABILITY_ADMIN = "graph/admin"
ABILITY_PIN = "graph/pin"
ABILITY_DELEGATE = "graph/delegate"

# Effect tags for MCP++ side-effect declarations
EFFECT_NONE = "graph.none"
EFFECT_READ = "graph.read"
EFFECT_QUERY = "graph.query"
EFFECT_WRITE = "graph.write"
EFFECT_ADMIN = "graph.admin"
EFFECT_STREAM = "graph.stream"
EFFECT_CANCEL = "graph.cancel"


def mcp_plus_metadata(
    *,
    ability: str,
    effects: Sequence[str],
    resource_template: str = "kg://{tenant}/{graph_id}",
    streaming: bool = False,
    cancellable: bool = False,
    mutates: bool = False,
) -> Dict[str, Any]:
    """Build MCP++ resource / effect metadata for a graph tool."""
    return {
        "mcp_plus_version": "kg-mcp-plus/v1",
        "resource_template": resource_template,
        "resource_scheme": "kg://",
        "ability": ability,
        "abilities": [ability],
        "effects": list(effects),
        "streaming": bool(streaming),
        "cancellable": bool(cancellable),
        "mutates": bool(mutates),
        "requires_explicit_target": True,
        "contract_version": CONTRACT_VERSION,
    }


def attach_mcp_plus(fn: Callable, meta: Mapping[str, Any]) -> Callable:
    """Attach MCP++ metadata as function attributes (discoverable by MCP++)."""
    payload = dict(meta)
    fn._mcp_plus = payload  # type: ignore[attr-defined]
    fn._mcp_plus_resource = payload.get("resource_template")  # type: ignore[attr-defined]
    fn._mcp_plus_effects = list(payload.get("effects") or [])  # type: ignore[attr-defined]
    fn._mcp_plus_ability = payload.get("ability")  # type: ignore[attr-defined]
    fn._mcp_plus_abilities = list(payload.get("abilities") or [])  # type: ignore[attr-defined]
    fn._mcp_plus_streaming = bool(payload.get("streaming"))  # type: ignore[attr-defined]
    fn._mcp_plus_cancellable = bool(payload.get("cancellable"))  # type: ignore[attr-defined]
    fn._mcp_plus_mutates = bool(payload.get("mutates"))  # type: ignore[attr-defined]
    return fn


def declare_mcp_plus(
    *,
    ability: str,
    effects: Sequence[str],
    resource_template: str = "kg://{tenant}/{graph_id}",
    streaming: bool = False,
    cancellable: bool = False,
    mutates: bool = False,
) -> Callable[[Callable], Callable]:
    """Decorator: attach MCP++ resource/effect metadata to a tool function."""

    meta = mcp_plus_metadata(
        ability=ability,
        effects=effects,
        resource_template=resource_template,
        streaming=streaming,
        cancellable=cancellable,
        mutates=mutates,
    )

    def decorator(fn: Callable) -> Callable:
        attach_mcp_plus(fn, meta)
        return fn

    return decorator


def error_envelope(
    operation: str,
    message: str,
    *,
    code: str = "INVALID_REQUEST",
    target: Optional[GraphTarget] = None,
    details: Optional[Mapping[str, Any]] = None,
    request_id: Optional[str] = None,
    retryable: bool = False,
) -> Dict[str, Any]:
    """Build a canonical lifecycle error envelope (JSON-safe)."""
    err = TypedError.of(
        code if code in {
            "INVALID_REQUEST", "INVALID_TARGET", "NOT_FOUND", "ALREADY_EXISTS",
            "CONFLICT", "FENCED", "UNAUTHORIZED", "FORBIDDEN", "BUDGET_EXCEEDED",
            "QUERY_PARSE", "QUERY_EXECUTION", "STORAGE", "INTEGRITY",
            "NOT_IMPLEMENTED", "INTERNAL",
        } else "INTERNAL",
        message,
        details=dict(details or {}),
        retryable=retryable,
    )
    result = LifecycleResult(
        status="error",
        operation=operation,
        target=target,
        error=err,
        request_id=request_id or f"req-{uuid.uuid4().hex}",
    )
    return _ensure_json_safe(result.to_json_dict())


def success_envelope(
    operation: str,
    *,
    target: Optional[GraphTarget],
    result: Optional[Mapping[str, Any]],
    request_id: Optional[str] = None,
    warnings: Optional[Sequence[str]] = None,
    authorization_receipt_ref: Optional[str] = None,
) -> Dict[str, Any]:
    lr = LifecycleResult(
        status="success",
        operation=operation,
        target=target,
        result=dict(result) if result is not None else {},
        warnings=tuple(warnings or ()),
        request_id=request_id or f"req-{uuid.uuid4().hex}",
        authorization_receipt_ref=authorization_receipt_ref,
    )
    return _ensure_json_safe(lr.to_json_dict())


def lifecycle_to_dict(result: LifecycleResult) -> Dict[str, Any]:
    return _ensure_json_safe(result.to_json_dict())


def _ensure_json_safe(obj: Any) -> Any:
    """Round-trip through JSON to guarantee serializability."""
    return json.loads(json.dumps(obj, allow_nan=False, default=str))


def resolve_target(
    *,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    profile: Optional[str] = None,
    require_graph: bool = True,
    default_branch: Optional[str] = None,
    for_list: bool = False,
    operation: str = "open",
) -> Tuple[Optional[GraphTarget], Optional[Dict[str, Any]]]:
    """Resolve an explicit GraphTarget from tool arguments.

    Returns ``(target, None)`` on success or ``(None, error_envelope)`` when
    the target is missing or invalid. Ambient / default graphs are never used.
    """
    gid = graph_id or graph
    stor = storage_profile or profile

    try:
        if target is not None:
            if isinstance(target, str):
                t = GraphTarget.from_uri(target, storage_profile=stor)
            elif isinstance(target, Mapping):
                if "uri" in target and not target.get("tenant"):
                    t = GraphTarget.from_uri(
                        str(target["uri"]),
                        storage_profile=stor or target.get("storage_profile"),
                    )
                else:
                    data = dict(target)
                    if stor and "storage_profile" not in data:
                        data["storage_profile"] = stor
                    t = GraphTarget.from_mapping(data)
            else:
                return None, error_envelope(
                    operation,
                    "target must be a kg:// URI string or mapping",
                    code="INVALID_TARGET",
                )
            # Field overrides
            if tenant and tenant != t.tenant:
                return None, error_envelope(
                    operation,
                    "tenant conflicts with target URI",
                    code="INVALID_TARGET",
                    details={"tenant": tenant, "target_tenant": t.tenant},
                )
            if gid and gid != t.graph_id:
                return None, error_envelope(
                    operation,
                    "graph_id conflicts with target URI",
                    code="INVALID_TARGET",
                    details={"graph_id": gid, "target_graph_id": t.graph_id},
                )
            if branch is not None and revision is not None:
                return None, error_envelope(
                    operation,
                    "branch and revision are mutually exclusive",
                    code="INVALID_TARGET",
                )
            if branch is not None:
                t = t.with_branch(str(branch))
            if revision is not None:
                t = t.with_revision(str(revision))
            if stor is not None and t.storage_profile != stor:
                t = t.with_profile(str(stor))
            return t, None

        # No target URI/mapping — require tenant (+ graph unless list).
        if not tenant:
            return None, error_envelope(
                operation,
                "explicit target required: pass target=kg://… or tenant (+ graph_id)",
                code="INVALID_TARGET",
                details={"hint": "GraphTarget is mandatory; no ambient graph"},
            )
        if for_list and not gid:
            gid = LIST_WILDCARD_GRAPH
        if require_graph and not gid:
            return None, error_envelope(
                operation,
                "explicit target required: graph_id (or target URI) is mandatory",
                code="INVALID_TARGET",
            )
        if not gid:
            gid = LIST_WILDCARD_GRAPH
        if branch is not None and revision is not None:
            return None, error_envelope(
                operation,
                "branch and revision are mutually exclusive",
                code="INVALID_TARGET",
            )
        if default_branch is not None and branch is None and revision is None:
            branch = default_branch
        t = GraphTarget(
            tenant=str(tenant),
            graph_id=str(gid),
            branch=str(branch) if branch is not None else None,
            revision=str(revision) if revision is not None else None,
            storage_profile=str(stor) if stor is not None else None,
        )
        return t, None
    except GraphTargetError as exc:
        return None, error_envelope(
            operation,
            exc.message,
            code="INVALID_TARGET",
            details={"target_code": exc.code, **exc.details},
        )
    except (TypeError, ValueError) as exc:
        return None, error_envelope(
            operation,
            str(exc),
            code="INVALID_TARGET",
        )


def resolve_auth(
    auth: Optional[Mapping[str, Any]] = None,
    *,
    principal: Optional[str] = None,
    tenant: Optional[str] = None,
    abilities: Optional[Sequence[str]] = None,
    ucan: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize per-call auth for GraphService authorizer."""
    out: Dict[str, Any] = dict(auth or {})
    if principal:
        out.setdefault("principal", principal)
    if tenant:
        out.setdefault("tenant", tenant)
    if abilities is not None:
        out["abilities"] = list(abilities)
    if ucan:
        out["ucan"] = ucan
    if token:
        out["token"] = token
    return out or None


def resolve_binding(
    *,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    store: Optional[str] = None,
    catalog: Optional[str] = None,
    operation: str = "open",
    legacy_driver_url: Optional[str] = None,
):
    """Resolve the server-owned GraphService binding."""
    cat = catalog_path or catalog
    stor = storage_path or store
    try:
        return get_graph_service_binding(
            catalog_path=cat,
            storage_path=stor,
        ), None
    except RuntimeError as exc:
        if legacy_driver_url:
            digest = hashlib.sha256(
                legacy_driver_url.encode("utf-8")
            ).hexdigest()[:16]
            root = (
                Path(tempfile.gettempdir())
                / "ipfs-datasets-py-legacy-mcp"
                / digest
            )
            root.mkdir(parents=True, exist_ok=True)
            try:
                return get_graph_service_binding(
                    catalog_path=root / "catalog.sqlite",
                    storage_path=root / "payloads",
                ), None
            except Exception as fallback_exc:
                exc = RuntimeError(str(fallback_exc))
        return None, error_envelope(
            operation,
            str(exc),
            code="INVALID_REQUEST",
            details={
                "env_catalog": ENV_CATALOG,
                "env_store": ENV_STORE,
            },
        )
    except Exception as exc:
        logger.exception("failed to resolve GraphService")
        return None, error_envelope(
            operation,
            f"failed to open GraphService: {exc}",
            code="STORAGE",
            retryable=True,
        )


def legacy_target_from_driver(driver_url: str) -> GraphTarget:
    """Map the deprecated driver URL identity to an explicit GraphTarget.

    Canonical calls never use this function; it exists only for old tool
    signatures that supply ``driver_url`` instead of ``target``.
    """
    digest = hashlib.sha256(driver_url.encode("utf-8")).hexdigest()[:16]
    return GraphTarget(
        tenant="legacy",
        graph_id=f"driver-{digest}",
        branch=DEFAULT_BRANCH,
    )


async def ensure_legacy_graph(binding: Any, target: GraphTarget) -> Optional[Dict[str, Any]]:
    """Idempotently create the deterministic legacy target."""
    result = await run_in_thread(
        binding.service.create,
        target,
        idempotency_key=f"legacy-create-{target.graph_id}",
    )
    payload = json_safe_result(result)
    if payload.get("status") == "success":
        return None
    error = payload.get("error") or {}
    if error.get("code") == "ALREADY_EXISTS":
        return None
    return payload


def run_sync(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run a sync GraphService call (tools are async wrappers)."""
    return fn(*args, **kwargs)


async def run_in_thread(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Execute a blocking GraphService method off the event loop."""
    try:
        import anyio

        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except ImportError:
        import asyncio

        return await asyncio.to_thread(fn, *args, **kwargs)


def json_safe_result(result: LifecycleResult) -> Dict[str, Any]:
    return lifecycle_to_dict(result)


async def load_snapshot_payload(
    *,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    operation: str = "query",
    require_target: bool = True,
) -> Tuple[Optional[GraphTarget], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load a graph snapshot via GraphService for specialized tools.

    Returns ``(target, kg_payload, error_envelope)``. Exactly one of
    ``kg_payload`` / ``error_envelope`` is set on success/failure when
    ``require_target`` is True.
    """
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        branch=branch,
        revision=revision,
        storage_profile=storage_profile,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=operation,
    )
    if err is not None:
        if require_target:
            return None, None, err
        return None, None, None

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=operation,
    )
    if berr is not None:
        return t, None, berr

    assert t is not None and binding is not None
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)
    try:
        # Prefer open then query-scan for entity payload.
        opened = await run_in_thread(
            binding.service.open_graph,
            t,
            auth=auth_map,
            request_id=request_id,
        )
        if not opened.ok:
            # Fallback: try query scan without open.
            q = await run_in_thread(
                binding.service.query,
                t if t.branch or t.revision else t.with_branch(DEFAULT_BRANCH),
                params={"language": "scan", "max_rows": 100_000},
                auth=auth_map,
                request_id=request_id,
                budgets={"max_rows": 100_000},
            )
            if not q.ok:
                return t, None, json_safe_result(opened if not opened.ok else q)
            payload = q.result or {}
            rows = payload.get("rows") or []
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
            return (
                q.target or t,
                {
                    "entities": entities,
                    "relationships": [],
                    "revision": payload.get("revision"),
                },
                None,
            )

        # Open succeeded — also fetch scan rows for entity list.
        qtarget = t if (t.branch or t.revision) else t.with_branch(DEFAULT_BRANCH)
        q = await run_in_thread(
            binding.service.query,
            qtarget,
            params={"language": "scan", "max_rows": 100_000},
            auth=auth_map,
            request_id=request_id,
            budgets={"max_rows": 100_000},
        )
        entities: List[Dict[str, Any]] = []
        revision = (opened.result or {}).get("revision")
        if q.ok and q.result:
            revision = q.result.get("revision") or revision
            for row in q.result.get("rows") or []:
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
        return (
            opened.target or t,
            {
                "entities": entities,
                "relationships": [],
                "revision": revision,
                "open": opened.result,
            },
            None,
        )
    except Exception as exc:
        logger.exception("load_snapshot_payload failed")
        return t, None, error_envelope(
            operation, str(exc), code="STORAGE", target=t, request_id=request_id
        )


def wrap_specialized_result(
    operation: str,
    *,
    target: Optional[GraphTarget],
    payload: Mapping[str, Any],
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize a specialized tool result into a lifecycle envelope."""
    status = str(payload.get("status") or "success")
    if status == "error":
        return error_envelope(
            operation,
            str(payload.get("message") or payload.get("error") or "error"),
            code=str(payload.get("code") or "INTERNAL"),
            target=target,
            details={k: v for k, v in payload.items() if k not in {"status", "message", "error", "code"}},
            request_id=request_id,
        )
    # Strip status from nested result to avoid duplication.
    body = {k: v for k, v in payload.items() if k != "status"}
    return success_envelope(
        operation,
        target=target,
        result=body,
        request_id=request_id,
    )


__all__ = [
    "DEFAULT_BRANCH",
    "LIST_WILDCARD_GRAPH",
    "ABILITY_LIST",
    "ABILITY_READ",
    "ABILITY_QUERY",
    "ABILITY_WRITE",
    "ABILITY_ADMIN",
    "ABILITY_PIN",
    "ABILITY_DELEGATE",
    "EFFECT_NONE",
    "EFFECT_READ",
    "EFFECT_QUERY",
    "EFFECT_WRITE",
    "EFFECT_ADMIN",
    "EFFECT_STREAM",
    "EFFECT_CANCEL",
    "mcp_plus_metadata",
    "attach_mcp_plus",
    "declare_mcp_plus",
    "error_envelope",
    "success_envelope",
    "lifecycle_to_dict",
    "json_safe_result",
    "resolve_target",
    "resolve_auth",
    "resolve_binding",
    "run_sync",
    "run_in_thread",
    "load_snapshot_payload",
    "wrap_specialized_result",
]
