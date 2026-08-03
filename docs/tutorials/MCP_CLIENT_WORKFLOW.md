# MCP client workflow tutorial

| Field | Value |
| --- | --- |
| Interface | `MCPClientTutorial@1` |
| Task | `IPFSDOC-084` |
| Status | `canonical` |
| Owner | tutorials / mcp-runtime |
| Audience | developer, agent, operator |
| Last verified | 2026-08-03 |
| Source of truth | `ipfs_datasets_py/mcp_server/` (`client.py`, `hierarchical_tool_manager.py`, `server_context.py`, `dispatch_pipeline.py`, `server.py`); architecture leaves under `docs/architecture/mcp/` |
| Related | [MCP_AND_RUNTIME.md](../api/domains/MCP_AND_RUNTIME.md), [SERVER_AND_DISPATCH.md](../architecture/mcp/SERVER_AND_DISPATCH.md), [TOOL_LIFECYCLE_AND_REGISTRIES.md](../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md), [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md), [LOGIC_AND_PROOF_WORKFLOW.md](LOGIC_AND_PROOF_WORKFLOW.md) |

## 1. Purpose

This tutorial is a **bounded local route** through the MCP client/service
plane without requiring a remote network peer:

1. **Discovery** — list categories and tools.
2. **Capability probe** — fetch schemas and interpret availability.
3. **Invocation** — dispatch a safe, local tool with a timeout budget.
4. **Denial** — show policy/pipeline deny without tool execution.
5. **Unavailable** — show missing-tool / missing-backend envelopes.
6. **Result receipt** — read `status`, `request_id`, and domain fields.

The preferred local route is the hierarchical tool manager (process-local),
the same surface the HTTP/stdio server exposes via meta-tools
`tools_list_categories`, `tools_list_tools`, `tools_get_schema`, and
`tools_dispatch`. Remote `IPFSDatasetsMCPClient("http://…")` is optional and
documented as a secondary path.

```text
  client / host
       │
       ▼
  discover categories ──► list tools ──► get schema
       │
       ▼
  optional pipeline.check(intent) ──deny──► error receipt (no execute)
       │ allow / no pipeline
       ▼
  dispatch(category, tool, params)
       │
       ├── success envelope + request_id
       ├── not found / unavailable
       └── execution error
```

## 2. Learning objectives

After this tutorial you can:

- Run discovery and schema probes fully offline via
  `HierarchicalToolManager`.
- Invoke a low-risk local tool and read the result envelope.
- Distinguish **listed** vs **executable** vs **policy-allowed**.
- Attach a deny stage and confirm non-execution.
- Handle unavailable tools and backends without inventing success.
- State prerequisites, timeouts, cleanup, redaction, and side effects.

## 3. Prerequisites, timeouts, cleanup, redaction, side effects

### 3.1 Software prerequisites

| Layer | Requirement | Optional? |
| --- | --- | --- |
| Python package | `ipfs_datasets_py` with `mcp_server` tree | Required |
| Hierarchical manager | `mcp_server.hierarchical_tool_manager` | Required (bounded local route) |
| Server context | `mcp_server.server_context.ServerContext` | Recommended for cleanup hooks |
| Dispatch pipeline | `mcp_server.dispatch_pipeline` | Optional; required for §7 deny demo |
| MCP SDK / HTTP client | `modelcontextprotocol` / network server | **Optional** remote path |
| FastAPI / Flask hosts | For `start_server` HTTP bind | **Optional** |
| Domain backends (IPFS, Neo4j, LLM, …) | Per-tool extras | **Optional**; missing → unavailable |

Install guidance when the MCP SDK is missing: import of
`IPFSDatasetsMCPClient` may be `None` or fall back to a test mock. Prefer the
hierarchical manager for offline tutorials.

### 3.2 Timeouts (recommended bounds)

| Operation | Suggested bound | Where |
| --- | --- | --- |
| Category / tool list | ≤ 5 s | Local disk discovery |
| Schema build | ≤ 5 s first call (then cache) | `get_tool_schema` |
| Default tool budget | **30 s** | `ServerConfig.tool_timeout_seconds` |
| Tutorial dispatch | 2–10 s | Pass small params; avoid heavy tools |
| Graceful shutdown | 5–30 s | `HierarchicalToolManager.graceful_shutdown` |
| Remote HTTP client | host-dependent | Only if using §9 remote path |

Metadata may override per-tool `timeout_seconds`. Circuit breakers open after
repeated failures (`failure_threshold` / `recovery_timeout` on the manager).

### 3.3 Side effects

| Surface | Side effects |
| --- | --- |
| `list_categories` / `list_tools` | Disk scan under `mcp_server/tools/`; may import category modules |
| `get_tool_schema` | Import tool module; populate schema cache |
| `dispatch` | **Runs the tool** — filesystem, network, GPU, or wallet effects depend on the tool |
| `ServerContext` enter | Initializes tool manager / metadata registry; optional P2P / scheduler |
| `start_server` / `start_stdio_server` | Binds ports or owns stdio; process-long loop |
| `IPFSDatasetsMCPClient` | Network I/O to `server_url` |
| Pipeline deny | **No** tool execution when attached and short-circuiting |
| Error reporting | Sanitizes kwargs (token/password/secret keys → `<REDACTED>`) |

**Safety rule for this tutorial:** only dispatch tools that are clearly
read-only or self-contained demos (for example `bespoke_tools.system_status`
or `bespoke_tools.cache_stats`). Do not dispatch `cli.execute_command`,
wallet, pin, or delete tools from a copy-paste session.

### 3.4 Cleanup

```python
# Prefer ServerContext so registered cleanup handlers run on exit.
# Discovery/dispatch APIs on HierarchicalToolManager are async — use them
# (or meta-tools), not the sync ctx.list_tools() helper which currently
# iterates async coroutines without awaiting and is not a reliable tutorial path.
from ipfs_datasets_py.mcp_server.server_context import ServerContext, ServerConfig
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

config = ServerConfig(tool_timeout_seconds=10.0, lazy_load_tools=True)
with ServerContext(config) as ctx:
    manager = ctx.tool_manager or HierarchicalToolManager()
    # categories = await manager.list_categories(include_count=True)
    # ... work via await manager.dispatch / get_tool_schema ...
# __exit__ runs _cleanup and FIFO cleanup handlers
```

Also:

- Call `await manager.graceful_shutdown(timeout=5)` if you constructed a
  long-lived manager with background work.
- Do not leave a bound HTTP port from `start_server` when experimenting —
  stop the process cleanly.
- Drop temporary datasets/indices created by dataset tools.
- Prefer constructing `HierarchicalToolManager()` directly when you only need
  the bounded local route and do not need ServerContext lifecycle hooks.

### 3.5 Redaction

- Never log raw `Authorization`, API keys, cookies, or wallet seed material
  from tool params.
- Server-side `_sanitize_error_context` redacts keys matching
  token/password/secret patterns and truncates large values — **client code
  should still redact before printing**.
- Prefer `request_id` + status in shared tickets over full param dumps.
- For logic/legal tools, prefer digests of source text (see
  [LOGIC_AND_PROOF_WORKFLOW.md](LOGIC_AND_PROOF_WORKFLOW.md)).

### 3.6 Core inequalities

| Observation | Does **not** mean |
| --- | --- |
| Tool name listed | Backend present / call will succeed |
| Schema returned | Policy allow |
| HTTP `/health` green | Tool executed successfully |
| `status=success` on tool | Domain theorem proof or wallet grant |
| Pipeline missing | Authorization approved |
| Flat `category.tool` alias | Second registry of truth |

## 4. Bounded local route (canonical for this tutorial)

### 4.1 Why local hierarchical first

| Route | Transport | When to use |
| --- | --- | --- |
| **`HierarchicalToolManager`** | In-process | Offline agents, unit demos, this tutorial |
| Meta-tools on `IPFSDatasetsMCPServer` | stdio / HTTP | IDE agents, remote hosts |
| `IPFSDatasetsMCPClient(url)` | HTTP to server | Integration against a running server |
| `SimpleIPFSDatasetsMCPServer` | Compatibility | Legacy only — not canonical |

Discovery authority is the **live tree** under
`ipfs_datasets_py/mcp_server/tools/`, not undated marketing catalogs.

### 4.2 Imports

```python
import asyncio
from typing import Any, Mapping

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    tools_list_categories,
    tools_list_tools,
    tools_get_schema,
    tools_dispatch,
)
```

The `tools_*` helpers are the same callables registered as MCP meta-tools;
they delegate to `get_tool_manager()`.

## 5. Step 1 — Discovery

```python
async def discover(manager: HierarchicalToolManager) -> dict[str, Any]:
    categories = await manager.list_categories(include_count=True)
    # categories: list[{"name", "description", "lazy", "tool_count"}, ...]

    nonempty = [c for c in categories if c.get("tool_count", 0) > 0]
    sample_category = "bespoke_tools"
    listed = await manager.list_tools(sample_category)
    # listed: {"status", "category", "tool_count", "tools": [{"name", "description"}, ...]}

    return {
        "category_count": len(categories),
        "nonempty_count": len(nonempty),
        "sample_category": sample_category,
        "sample_list_status": listed.get("status"),
        "sample_tools": [
            t.get("name") for t in listed.get("tools", []) if isinstance(t, dict)
        ],
    }


async def main_discover() -> None:
    manager = HierarchicalToolManager()
    print(await discover(manager))


# asyncio.run(main_discover())
```

**Receipt fields to keep:** category names, tool names, `tool_count`. Do not
assume every listed tool imports cleanly on first dispatch.

Equivalent meta-tool style:

```python
async def discover_via_meta() -> Any:
    return await tools_list_categories(include_count=True)
```

## 6. Step 2 — Capability probe (schema)

```python
async def probe_schema(
    manager: HierarchicalToolManager,
    category: str,
    tool: str,
) -> dict[str, Any]:
    envelope = await manager.get_tool_schema(category, tool)
    # Canonical hierarchical envelope:
    #   success → {"status": "success", "schema": {name, category, description, ...}}
    #   miss    → {"status": "error", "error": "Tool '…' not found in category '…'"}
    if not isinstance(envelope, dict):
        return {
            "category": category,
            "tool": tool,
            "probe": "degraded",
            "schema_type": type(envelope).__name__,
        }

    status = envelope.get("status")
    body = envelope.get("schema") if status == "success" else None
    return {
        "category": category,
        "tool": tool,
        "status": status,
        "error": envelope.get("error"),
        "has_schema_body": isinstance(body, dict),
        "schema_name": (body or {}).get("name") if isinstance(body, dict) else None,
        "schema_preview": str(body or envelope)[:400],
    }


async def main_probe() -> None:
    manager = HierarchicalToolManager()
    print(await probe_schema(manager, "bespoke_tools", "system_status"))
    print(await probe_schema(manager, "bespoke_tools", "no_such_tool"))


# asyncio.run(main_probe())
```

Interpretation:

| Probe result | Meaning |
| --- | --- |
| `status=success` + nested `schema` | Tool module importable enough to describe |
| `status=error` / not found | Treat capability as missing before invoke |
| Empty category tool list | Discovery gap; do not invent tools |
| Schema present | Still not policy allow or domain success |

Capability probe ≠ policy allow ≠ successful domain execution.

## 7. Step 3 — Invocation and result receipt

### 7.1 Safe local invoke

```python
async def invoke_safe(manager: HierarchicalToolManager) -> Mapping[str, Any]:
    result = await manager.dispatch(
        "bespoke_tools",
        "system_status",
        {},  # keep params empty / non-sensitive
    )
    return result


def summarize_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize hierarchical dispatch envelopes for agents."""
    status = result.get("status")
    if status is None and result.get("success") is True:
        status = "success"
    if status is None and result.get("success") is False:
        status = "error"

    return {
        "status": status,
        "request_id": result.get("request_id"),
        "error": result.get("error"),
        "success_flag": result.get("success"),
        "top_level_keys": sorted(result.keys()),
    }


async def main_invoke() -> None:
    manager = HierarchicalToolManager()
    raw = await invoke_safe(manager)
    print(summarize_receipt(raw))
    # Domain-specific fields (hostname, metrics, …) stay in raw; redaction applies
    # before sharing logs.


# asyncio.run(main_invoke())
```

### 7.2 Receipt patterns (canonical)

| Pattern | Typical fields |
| --- | --- |
| Success (dict tool, e.g. `system_status`) | Domain keys + `success=True` + `request_id` (may **omit** top-level `status`) |
| Success (non-dict tool) | `status=success`, `result=<str>`, `request_id` |
| Not found | `status=error`, `error` containing `not found`, `available_tools`, `request_id` |
| Execution error | `status=error`, `error`, optional `category`/`tool`, `request_id` |
| Cache hit | Prior payload + `_cached=true` |
| Traced | Plus `trace` / `_trace` metadata (not proof authority) |

Always persist **`request_id` + derived status** for support correlation. Use
`summarize_receipt` so dict-success tools that only set `success=True` still
normalize to a status label agents can switch on.

## 8. Step 4 — Unavailable outcomes

### 8.1 Missing tool name

```python
async def unavailable_tool(manager: HierarchicalToolManager) -> Mapping[str, Any]:
    return await manager.dispatch(
        "dataset_tools",
        "nonexistent_xyz",
        {},
    )


async def main_unavailable() -> None:
    manager = HierarchicalToolManager()
    result = await unavailable_tool(manager)
    assert result.get("status") == "error"
    assert "not found" in str(result.get("error", "")).lower()
    print(
        {
            "status": result.get("status"),
            "error": result.get("error"),
            "available_tools": result.get("available_tools"),
            "request_id": result.get("request_id"),
        }
    )


# asyncio.run(main_unavailable())
```

### 8.2 Missing backend / optional extra

When a tool is listed but an optional engine is absent, dispatch often
returns a domain error envelope (`status=error` or `success=False` with an
“unavailable” / `ImportError` message). **Discovery may still list the
name.** Agents must:

1. Read the error envelope.
2. Surface **unavailable** to the user.
3. Not retry indefinitely (circuit breaker may open).

```python
def classify_tool_outcome(result: Mapping[str, Any]) -> str:
    if result.get("status") == "error" or result.get("success") is False:
        err = str(result.get("error") or result.get("message") or "").lower()
        if "not found" in err:
            return "unavailable_tool"
        if "unavailable" in err or "importerror" in err or "not installed" in err:
            return "unavailable_backend"
        return "execution_error"
    if result.get("status") == "success" or result.get("success") is True:
        return "ok"
    return "unknown_envelope"
```

## 9. Step 5 — Denial (pipeline, no execution)

Attach a fail-closed stage that denies before dispatch. This models policy /
compliance short-circuit behavior described in
[POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md).

```python
from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
    DispatchPipeline,
    PipelineStage,
)


def deny_stage(intent: dict) -> dict:
    return {
        "allowed": False,
        "reason": "tutorial-policy-deny",
        "stage": "tutorial_policy",
    }


def build_denying_pipeline() -> DispatchPipeline:
    return DispatchPipeline(
        stages=[
            PipelineStage(
                name="tutorial_policy",
                handler=deny_stage,
                enabled=True,
                fail_open=False,
            )
        ],
        # short_circuit defaults keep later stages from running after deny
    )


def check_intent_or_deny(pipeline: DispatchPipeline, tool_name: str) -> dict:
    # Legacy stage pipelines: use run() so custom PipelineStage handlers execute.
    # Integrated MCP++ mode uses check() with PipelineConfig feature flags instead.
    intent = {
        "tool": tool_name,
        "tool_name": tool_name,
        "actor": "tutorial",
        "params": {},
    }
    decision = pipeline.run(intent)
    allowed = bool(getattr(decision, "allowed", False))
    return {
        "tool": tool_name,
        "allowed": allowed,
        "denied_by": getattr(decision, "denied_by", None),
        "stages_executed": getattr(decision, "stages_executed", []),
        "decision_type": type(decision).__name__,
    }


def demo_denial() -> dict:
    pipeline = build_denying_pipeline()
    receipt = check_intent_or_deny(pipeline, "bespoke_tools.system_status")
    if not receipt["allowed"]:
        # CRITICAL: do not call manager.dispatch when denied.
        receipt["executed"] = False
        receipt["note"] = "deny short-circuits tool execution"
    return receipt


# print(demo_denial())
# Expected: allowed=False, denied_by='tutorial_policy', executed=False
```

On a full `IPFSDatasetsMCPServer` with `set_pipeline(...)`, denied
`tools_dispatch` calls return an error dict **without** running the domain
tool. Listing still works — discovery is not authorization.

| API | Mode | Use for this tutorial |
| --- | --- | --- |
| `DispatchPipeline(stages=[...]).run(intent)` | **Legacy** custom stages | Explicit deny-stage demo |
| `DispatchPipeline(config=PipelineConfig(...)).check(intent)` | Integrated MCP++ | Compliance/risk/policy flags |

Do not call `check()` expecting legacy `PipelineStage` handlers to run — with
no `PipelineConfig` flags enabled, `check()` pass-through-allows.

## 10. End-to-end local journey

```python
"""Bounded MCP local route: discover → probe → invoke → unavailable → deny."""

from __future__ import annotations

import asyncio
from typing import Any

from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
    DispatchPipeline,
    PipelineStage,
)
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
)
from ipfs_datasets_py.mcp_server.server_context import ServerConfig, ServerContext


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    sensitive = ("token", "password", "secret", "authorization", "api_key")
    out: dict[str, Any] = {}
    for key, value in params.items():
        if any(s in key.lower() for s in sensitive):
            out[key] = "<REDACTED>"
        else:
            out[key] = value
    return out


async def journey() -> dict[str, Any]:
    config = ServerConfig(tool_timeout_seconds=10.0, lazy_load_tools=True)
    with ServerContext(config) as ctx:
        manager = ctx.tool_manager or HierarchicalToolManager()

        categories = await manager.list_categories(include_count=True)
        tools = await manager.list_tools("bespoke_tools")
        schema = await manager.get_tool_schema("bespoke_tools", "system_status")

        # Capability probe: hierarchical envelope with nested schema body
        probed = (
            isinstance(schema, dict)
            and schema.get("status") == "success"
            and isinstance(schema.get("schema"), dict)
        )

        # Invocation (safe tool — success may set success=True without status)
        invoked = await manager.dispatch("bespoke_tools", "system_status", {})
        invoke_receipt = {
            "status": invoked.get("status")
            or (
                "success"
                if invoked.get("success") is True
                else ("error" if invoked.get("success") is False else "unknown")
            ),
            "request_id": invoked.get("request_id"),
            "success": invoked.get("success"),
        }

        # Unavailable tool
        missing = await manager.dispatch("audit_tools", "definitely_missing_tool_xyz", {})
        missing_receipt = {
            "status": missing.get("status"),
            "error": missing.get("error"),
            "available_tools": missing.get("available_tools"),
            "request_id": missing.get("request_id"),
        }

        # Denial without execution (legacy stage pipeline → use run())
        pipeline = DispatchPipeline(
            stages=[
                PipelineStage(
                    name="tutorial_policy",
                    handler=lambda intent: {
                        "allowed": False,
                        "reason": "tutorial-deny",
                        "stage": "tutorial_policy",
                    },
                    fail_open=False,
                )
            ]
        )
        decision = pipeline.run(
            {
                "tool": "bespoke_tools.system_status",
                "tool_name": "bespoke_tools.system_status",
                "actor": "tutorial",
                "params": _redact_params({"api_key": "should-not-appear"}),
            }
        )
        allowed = bool(getattr(decision, "allowed", False))

        return {
            "discovery": {
                "categories": len(categories),
                "bespoke_tool_count": tools.get("tool_count"),
            },
            "capability_probe_ok": probed,
            "invocation": invoke_receipt,
            "unavailable": missing_receipt,
            "denial": {
                "allowed": allowed,
                "denied_by": getattr(decision, "denied_by", None),
                "executed": False,
            },
            "timeouts": {"tool_timeout_seconds": config.tool_timeout_seconds},
            "cleanup": "ServerContext.__exit__",
            "side_effects": "read-only status tool + local discovery imports",
        }


if __name__ == "__main__":
    import json
    print(json.dumps(asyncio.run(journey()), indent=2, default=str))
```

## 11. Optional remote client path

Use only when a server is already running (not required for acceptance of
this tutorial).

```python
# Server (separate process):
# from ipfs_datasets_py.mcp_server import start_server
# start_server(host="127.0.0.1", port=8000)

import asyncio
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient

async def remote_list(url: str = "http://127.0.0.1:8000") -> list:
    if IPFSDatasetsMCPClient is None:
        raise RuntimeError("MCP client dependency unavailable")
    client = IPFSDatasetsMCPClient(url)
    return await client.get_available_tools()

# Tools may appear as hierarchical meta-tools; prefer tools_dispatch semantics:
# await client.call_tool("tools_list_categories", {"include_count": True})
# await client.call_tool(
#     "tools_dispatch",
#     {"category": "bespoke_tools", "tool": "system_status", "params": {}},
# )
```

**Unavailable remote:** connection errors, mock client fallbacks, or
`IPFSDatasetsMCPClient is None` must be reported as transport/dependency
unavailable — not as a successful empty inventory.

Convenience methods on the client (`load_dataset`, `pin_to_ipfs`, …) are
thin wrappers around `call_tool` with **side effects** on the server host.
Prefer meta-tools for discovery; treat convenience methods as domain sugar.

## 12. CLI / process entry (operator note)

```bash
# stdio MCP loop (IDE hosts)
python -m ipfs_datasets_py.mcp_server
# or
python -c "from ipfs_datasets_py.mcp_server import start_stdio_server; start_stdio_server()"

# HTTP bind — side effect: listens on host:port
python -c "from ipfs_datasets_py.mcp_server import start_server; start_server(host='127.0.0.1', port=8000)"
```

Stop with process signal; do not leave orphan listeners in shared CI hosts.

## 13. Verification commands

```bash
# Tutorials present and non-empty (task gate)
test -s docs/tutorials/MCP_CLIENT_WORKFLOW.md

# Syntax-check tutorials tree (task gate)
python -m compileall -q docs/tutorials

# Optional live local discovery (environment-dependent)
python - <<'PY'
import asyncio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

async def main():
    m = HierarchicalToolManager()
    cats = await m.list_categories(include_count=True)
    print("categories", len(cats))
    missing = await m.dispatch("audit_tools", "definitely_missing_tool_xyz", {})
    print("missing_status", missing.get("status"), missing.get("error"))

asyncio.run(main())
PY
```

## 14. Next steps

- API map: [MCP_AND_RUNTIME.md](../api/domains/MCP_AND_RUNTIME.md).
- Lifecycle and envelopes:
  [TOOL_LIFECYCLE_AND_REGISTRIES.md](../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md).
- Policy stages:
  [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md).
- Logic tools over MCP after local authority rules:
  [LOGIC_AND_PROOF_WORKFLOW.md](LOGIC_AND_PROOF_WORKFLOW.md).
