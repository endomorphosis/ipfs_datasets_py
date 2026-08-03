# MCP client workflow

| Field | Value |
| --- | --- |
| Interface | `MCPClientTutorial@1` |
| Task | `IPFSDOC-084` |
| Status | `canonical` |
| Owner | tutorials / MCP runtime plane |
| Last verified | 2026-08-03 |
| Audience | developer, agent, offline operator, security reviewer |
| Related | [MCP_AND_RUNTIME.md](../api/domains/MCP_AND_RUNTIME.md), [mcp/README.md](../architecture/mcp/README.md), [SERVER_AND_DISPATCH.md](../architecture/mcp/SERVER_AND_DISPATCH.md), [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md), [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md), [ADR-007](../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |

> **Purpose.** Bounded, **local-first** journey through MCP **discovery**,
> **capability probe**, **invocation**, **denial**, **unavailable** labeling,
> and **result receipt** handling. The verified route is the in-process
> `HierarchicalToolManager` (no required HTTP daemon). Declares service
> prerequisites, timeouts, cleanup, redaction, and side effects. Transport
> 200 / tool list presence is **never** domain success or policy allow.

**Upstream tutorials:** [FIRST_DATASET_WORKFLOW.md](FIRST_DATASET_WORKFLOW.md)
for local dataset patterns. Logic/proof authority is covered in
[LOGIC_AND_PROOF_WORKFLOW.md](LOGIC_AND_PROOF_WORKFLOW.md) — this page does not
redefine theorem proof.

---

## 1. Learning objectives

1. Declare MCP SDK / server prerequisites and degrade when the HTTP client is missing.
2. Use the **bounded local route**: `HierarchicalToolManager` discovery + dispatch.
3. Probe categories, tools, and schemas (capability probe).
4. Invoke a safe local tool and record a typed result receipt.
5. Exercise **denial** (unknown tool / category) and **unavailable** (missing deps, missing client).
6. Separate pipeline deny, tool error, and domain success.
7. Apply timeouts, cleanup, and redaction rules for audit-shaped payloads.

---

## 2. Prerequisites and declared extras

### 2.1 Minimum (bounded local route)

| Requirement | Notes |
| --- | --- |
| Python ≥ 3.12 | Project requirement |
| `pip install -e .` | Package importable from repo root |
| Write access to temp dir | Tutorial artifacts only under `tempfile` |

```bash
pip install -e .
```

No MCP HTTP server and no IPFS daemon are required for the **verified local
route**.

### 2.2 Optional service / SDK extras

| Extra / dependency | Enables | If missing |
| --- | --- | --- |
| `mcp` / `modelcontextprotocol` + `anyio` | Real `IPFSDatasetsMCPClient` over HTTP | Package export may be `None`; use hierarchical manager |
| Live `IPFSDatasetsMCPServer` on `127.0.0.1:8000` | Network client demos | Skip HTTP path; do not invent tools |
| Hugging Face `datasets` | `load_dataset` tool success | Tool returns **error** envelope (unavailable dep) |
| `flask` / FastAPI stack | Simple or full HTTP servers | Local hierarchical path still works |
| gRPC / P2P / MCP++ | Alternate carriers | **Optional**; out of scope for this tutorial |

```bash
# Optional HTTP client path only
pip install anyio mcp
# Optional dataset hub path (not required here)
# pip install datasets
```

### 2.3 Timeouts (declared budgets)

| Surface | Tutorial budget | Notes |
| --- | --- | --- |
| Hierarchical `dispatch` | rely on tool metadata / defaults | Prefer fast tools (`audit_tools`, local save) |
| HTTP client (optional) | connect/read ≤ 10s recommended | Fail closed on timeout — do not retry forever |
| `graceful_shutdown` | manager default | Call when shutting a long-lived manager |
| Capability list/schema | sub-second expected offline | Large trees may take longer first import |

---

## 3. Bounded local route (canonical for this tutorial)

```text
  HierarchicalToolManager  (in-process)
           │
           ├─ list_categories / list_tools     → discovery
           ├─ get_tool_schema                 → capability probe
           ├─ dispatch(category, tool, params)→ invocation
           └─ error envelopes                 → denial / unavailable

  Optional: IPFSDatasetsMCPClient("http://127.0.0.1:8000")
           only when server + MCP SDK are present
```

**Why local-first:** the package may export `IPFSDatasetsMCPClient = None` when
MCP client deps are missing. Discovery still works against the on-disk tool
tree under `ipfs_datasets_py/mcp_server/tools/`.

```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

# Optional HTTP client — may be None
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient
```

**Core inequalities**

- category/tool **listed** ≠ optional backend present
- schema **CID** / signature ≠ authorization
- pipeline **allow** ≠ domain `status=success`
- HTTP 200 ≠ tool succeeded
- mock / simple server ≠ canonical architecture

---

## 4. Offline workspace setup

```python
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

WORK = Path(tempfile.mkdtemp(prefix="mcp_client_workflow_"))
RECEIPTS = WORK / "receipts"
RECEIPTS.mkdir(parents=True, exist_ok=True)
print("workspace", WORK)
```

Cleanup requirement: remove `WORK` at the end of every full run (§11–§12).

---

## 5. Discovery

```python
import asyncio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager


async def discover(manager: HierarchicalToolManager) -> Dict[str, Any]:
    categories = await manager.list_categories(include_count=True)
    assert isinstance(categories, list) and len(categories) > 0
    nonempty = [c for c in categories if int(c.get("tool_count") or 0) > 0]
    # Prefer a known offline-friendly category for later steps
    dataset = await manager.list_tools("dataset_tools")
    audit = await manager.list_tools("audit_tools")
    logic = await manager.list_tools("logic_tools")
    evidence = {
        "category_count": len(categories),
        "nonempty_category_count": len(nonempty),
        "dataset_tool_count": dataset.get("tool_count"),
        "audit_tool_count": audit.get("tool_count"),
        "logic_tool_count": logic.get("tool_count"),
        "dataset_tools": [t.get("name") for t in dataset.get("tools") or []],
        "audit_tools": [t.get("name") for t in audit.get("tools") or []],
        # Hierarchical discovery matches function name to file stem; many
        # logic_*_tool.py modules expose functions without the _tool suffix and
        # may report tool_count=0 here even though modules exist on disk.
        "logic_discovery_note": "zero_count_possible_name_mismatch_not_domain_absence",
    }
    print("discovery", evidence)
    (RECEIPTS / "discovery.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    return evidence
```

| Observation | Reading |
| --- | --- |
| `category_count` large | Tree scanned — inventory is live, not a marketing catalog |
| `logic_tool_count == 0` | Possible hierarchical name mismatch; modules may still import directly |
| Empty category | Not an error; do not invent tools |

Direct import fallback for logic capability tools (when hierarchical list is empty):

```python
from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
    logic_capabilities,
    logic_health,
)

# caps = await logic_capabilities()
# health = await logic_health()
```

---

## 6. Capability probe (schema)

```python
async def capability_probe(manager: HierarchicalToolManager) -> Dict[str, Any]:
    schema = await manager.get_tool_schema("dataset_tools", "load_dataset")
    audit_schema = await manager.get_tool_schema("audit_tools", "record_audit_event")
    missing = await manager.get_tool_schema("dataset_tools", "no_such_tool_xyz")
    probes = {
        "load_dataset_status": schema.get("status"),
        "load_dataset_has_schema": isinstance(schema.get("schema"), dict),
        "record_audit_event_status": audit_schema.get("status"),
        "missing_tool_status": missing.get("status"),
        "missing_tool_error": missing.get("error"),
    }
    print("capability_probe", probes)
    # Redact full parameter defaults if they ever embed secrets (none expected here)
    (RECEIPTS / "schemas_summary.json").write_text(
        json.dumps(probes, indent=2), encoding="utf-8"
    )
    return probes
```

Schema success means the function was introspected — **not** that backends or
policy allow execution.

---

## 7. Invocation and result receipt

### 7.1 Safe local success path: audit event

`audit_tools.record_audit_event` is a good bounded local invoke: no hub, no
daemon, returns a structured receipt.

```python
async def invoke_audit(manager: HierarchicalToolManager) -> Dict[str, Any]:
    result = await manager.dispatch(
        "audit_tools",
        "record_audit_event",
        {
            "action": "tutorial.mcp_client.probe",
            "resource_type": "tutorial",
            "resource_id": "mcp-client-workflow",
            # Do not put secrets, tokens, or PII into details in shared logs
            "details": {"purpose": "bounded_local_route", "side_effect": "audit_log"},
            "severity": "info",
            "tags": ["tutorial", "mcp_client_workflow"],
        },
    )
    receipt = {
        "status": result.get("status"),
        "event_id": result.get("event_id"),
        "action": result.get("action"),
        "request_id": result.get("request_id"),
        "disposition": (
            "domain_success"
            if result.get("status") == "success"
            else "tool_error_or_unavailable"
        ),
    }
    print("invoke_audit", receipt)
    (RECEIPTS / "invoke_audit.json").write_text(
        json.dumps({"receipt": receipt, "raw_keys": list(result.keys())}, indent=2),
        encoding="utf-8",
    )
    return receipt
```

### 7.2 Domain unavailable example: `load_dataset` without HF

When Hugging Face `datasets` is missing, dispatch still **runs** but returns an
error envelope. Label it **unavailable**, not denial of existence.

```python
async def invoke_load_dataset_unavailable(
    manager: HierarchicalToolManager, sample_path: Path
) -> Dict[str, Any]:
    result = await manager.dispatch(
        "dataset_tools",
        "load_dataset",
        {"source": str(sample_path), "format": "json"},
    )
    message = str(result.get("message") or result.get("error") or "")
    unavailable = "datasets" in message.lower() or result.get("status") == "error"
    labeled = {
        "status": result.get("status"),
        "message_redacted": message[:160],
        "disposition": "dependency_unavailable" if unavailable else "other_error_or_success",
        "request_id": result.get("request_id"),
    }
    print("invoke_load_dataset", labeled)
    return labeled
```

### 7.3 Optional local write: `save_dataset`

```python
async def invoke_save_dataset(
    manager: HierarchicalToolManager, destination: Path
) -> Dict[str, Any]:
    payload = [{"id": "a", "text": "MCP local route sample"}]
    result = await manager.dispatch(
        "dataset_tools",
        "save_dataset",
        {
            "dataset_data": payload,
            "destination": str(destination),
            "format": "json",
        },
    )
    labeled = {
        "status": result.get("status"),
        "destination": result.get("destination") or result.get("location"),
        "size": result.get("size"),
        "request_id": result.get("request_id"),
        "disposition": (
            "domain_success"
            if result.get("status") == "success"
            else "tool_error_or_unavailable"
        ),
    }
    print("invoke_save_dataset", labeled)
    return labeled
```

---

## 8. Denial paths (fail closed)

Denial means the **manager refused the call** (unknown category/tool), not that
a domain engine rejected business logic.

```python
async def denial_paths(manager: HierarchicalToolManager) -> Dict[str, Any]:
    missing_tool = await manager.dispatch(
        "dataset_tools", "no_such_tool_xyz", {}
    )
    missing_category = await manager.dispatch(
        "no_category_xyz", "load_dataset", {}
    )
    denials = {
        "missing_tool_status": missing_tool.get("status"),
        "missing_tool_error": missing_tool.get("error"),
        "missing_tool_available_sample": (missing_tool.get("available_tools") or [])[:5],
        "missing_category_status": missing_category.get("status"),
        "missing_category_error": missing_category.get("error"),
        "disposition": "dispatch_denial_not_domain_engine",
    }
    print("denial", denials)
    (RECEIPTS / "denial.json").write_text(
        json.dumps(denials, indent=2), encoding="utf-8"
    )
    return denials
```

| Envelope | Kind |
| --- | --- |
| `Tool '…' not found` + `available_tools` | **Denial** (unknown tool) |
| `Category '…' not found` + `available_categories` | **Denial** (unknown category) |
| `status=error` + missing library message | **Unavailable** dependency |
| Pipeline verdict deny (optional stages) | **Policy denial** — still not domain success |

Optional pipeline note (attach only when you run a full server):

```python
from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
    make_default_pipeline,
    make_full_pipeline,
)

# pipeline = make_default_pipeline()
# server.set_pipeline(pipeline)  # on IPFSDatasetsMCPServer — optional path
# Pipeline allow ≠ tool executed successfully; deny ≠ theorem about safety.
```

---

## 9. HTTP client path (optional / may be unavailable)

```python
from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient


async def optional_http_client(server_url: str = "http://127.0.0.1:8000") -> Dict[str, Any]:
    if IPFSDatasetsMCPClient is None:
        return {
            "disposition": "client_unavailable",
            "reason": "IPFSDatasetsMCPClient is None (MCP client deps missing)",
        }
    client = IPFSDatasetsMCPClient(server_url)
    try:
        # Bound your own wait externally if the transport lacks timeouts
        tools = await client.get_available_tools()
        return {
            "disposition": "client_reachable",
            "tool_count": len(tools) if tools is not None else 0,
            "note": "list presence ≠ domain success",
        }
    except Exception as exc:
        return {
            "disposition": "client_or_server_unavailable",
            "error_type": type(exc).__name__,
            "error_redacted": str(exc)[:160],
        }
```

Start a server only when you intentionally leave the offline path:

```bash
# Optional — binds a port; not required for §5–§8
python -m ipfs_datasets_py.mcp_server  # or start_server(host="127.0.0.1", port=8000)
```

**Side effects:** port bind, tool import from disk, optional ipfs_kit registration.

---

## 10. End-to-end local script (runnable)

Selected runnable journey: workspace → discovery → schema probe → audit invoke →
load_dataset unavailable label → denial paths → optional client check → cleanup.

```python
"""MCP client bounded local workflow (selected runnable snippet)."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="mcp_client_workflow_"))
    receipts = work / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    sample = work / "sample.json"
    sample.write_text(
        json.dumps([{"id": "a", "text": "MCP local route sample"}], indent=2),
        encoding="utf-8",
    )
    try:
        manager = HierarchicalToolManager()

        categories = await manager.list_categories(include_count=True)
        dataset = await manager.list_tools("dataset_tools")
        audit = await manager.list_tools("audit_tools")
        logic = await manager.list_tools("logic_tools")

        schema = await manager.get_tool_schema("dataset_tools", "load_dataset")
        missing_schema = await manager.get_tool_schema(
            "dataset_tools", "no_such_tool_xyz"
        )

        audit_result = await manager.dispatch(
            "audit_tools",
            "record_audit_event",
            {
                "action": "tutorial.mcp_client.probe",
                "resource_type": "tutorial",
                "resource_id": "mcp-client-workflow",
                "details": {"purpose": "bounded_local_route"},
                "severity": "info",
                "tags": ["tutorial"],
            },
        )

        load_result = await manager.dispatch(
            "dataset_tools",
            "load_dataset",
            {"source": str(sample), "format": "json"},
        )
        load_msg = str(load_result.get("message") or load_result.get("error") or "")

        missing_tool = await manager.dispatch(
            "dataset_tools", "no_such_tool_xyz", {}
        )
        missing_category = await manager.dispatch(
            "no_category_xyz", "load_dataset", {}
        )

        if IPFSDatasetsMCPClient is None:
            http_disp = "client_unavailable"
        else:
            http_disp = "client_class_importable_server_not_required"

        evidence = {
            "category_count": len(categories),
            "dataset_tool_count": dataset.get("tool_count"),
            "audit_tool_count": audit.get("tool_count"),
            "logic_tool_count": logic.get("tool_count"),
            "schema_load_dataset": schema.get("status"),
            "schema_missing_tool": missing_schema.get("status"),
            "audit_status": audit_result.get("status"),
            "audit_event_id_present": bool(audit_result.get("event_id")),
            "load_dataset_status": load_result.get("status"),
            "load_dataset_disposition": (
                "dependency_unavailable"
                if load_result.get("status") == "error"
                else "success_or_other"
            ),
            "load_message_redacted": load_msg[:160],
            "denial_missing_tool": missing_tool.get("status"),
            "denial_missing_category": missing_category.get("status"),
            "http_client_disposition": http_disp,
        }
        (receipts / "evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        print("evidence", evidence)
        assert evidence["category_count"] > 0
        assert evidence["schema_load_dataset"] == "success"
        assert evidence["audit_status"] == "success"
        assert evidence["denial_missing_tool"] == "error"
        assert evidence["denial_missing_category"] == "error"
    finally:
        shutil.rmtree(work, ignore_errors=True)
        print("cleanup", "removed_temp_workspace")


if __name__ == "__main__":
    asyncio.run(main())
```

**How to run**

```bash
python /tmp/mcp_client_workflow.py
```

**Expected evidence**

| Field | Expected local |
| --- | --- |
| `category_count` | `> 0` |
| `schema_load_dataset` | `success` |
| `schema_missing_tool` | `error` |
| `audit_status` | `success` |
| `audit_event_id_present` | `true` |
| `load_dataset_status` | Often `error` without HF `datasets` — labeled unavailable |
| `denial_missing_tool` / `denial_missing_category` | `error` |
| `http_client_disposition` | `client_unavailable` or importable-without-server |
| Cleanup | Temp dir removed |

---

## 11. Cleanup, redaction, and side effects

### 11.1 Cleanup

| Artifact | Action |
| --- | --- |
| Temp `WORK` / receipts / sample JSON | `shutil.rmtree(work, ignore_errors=True)` |
| `HierarchicalToolManager` | Drop reference; optional `await manager.graceful_shutdown()` for long sessions |
| Optional HTTP server process | Stop the process you started; do not leave port 8000 bound |
| Audit subsystem state | In-process; process exit clears unless a durable audit backend is configured |

### 11.2 Redaction

| Data | Guidance |
| --- | --- |
| `user_id`, `source_ip`, tokens in audit `details` | Prefer omit; never print secrets |
| Full `available_categories` lists | Truncate in shared logs (`[:5]` sample is enough) |
| Absolute filesystem paths | Prefer relative or temp basenames in published receipts |
| Tool error stack traces | Prefer `error_type` + short message |
| MCP auth headers (HTTP path) | Never log |

### 11.3 Side effects

| Action | Side effect |
| --- | --- |
| `list_categories` / `list_tools` | Disk discovery; import of tool modules |
| `dispatch` audit | May append to audit logger sinks |
| `dispatch` dataset save/load | Filesystem and/or optional hub |
| `start_server` / `start_stdio_server` | Bind port or take over stdio |
| Circuit breaker on repeated failures | Temporary isolation of a tool path |

---

## 12. Unavailable, denial, and success matrix

| Step | Success | Denial | Unavailable |
| --- | --- | --- | --- |
| Discovery | Categories/tools listed | — | Empty category / name-mismatch zero count |
| Schema probe | `status=success` + schema dict | Unknown tool schema error | Import failure of tool module |
| `record_audit_event` | `status=success` + `event_id` | Bad params validation | Audit backend hard-down (rare offline) |
| `load_dataset` | Domain success with data | — | Missing `datasets` library message |
| Unknown tool/category dispatch | — | `status=error` + available_* | — |
| `IPFSDatasetsMCPClient` | Tools listed from live server | Auth/policy deny if configured | Class `None` or connection error |
| Dispatch pipeline | Stage pass | Stage deny / soft-skip | Stage handler error |

---

## 13. Verification ledger (this tutorial)

| Item | Value |
| --- | --- |
| Owner | tutorials / IPFSDOC-084 |
| Source page | `docs/tutorials/MCP_CLIENT_WORKFLOW.md` |
| Setup | `pip install -e .`; MCP SDK optional |
| Bounded command | Run §10 script; `python -m compileall -q docs/tutorials` |
| Expected evidence | Discovery counts; schema success; audit success receipt; load_dataset unavailable labeled; denial errors; client disposition; cleanup |
| Network / native / service | No network required for local route; HTTP server optional |
| Last verified tree | task `IPFSDOC-084` (2026-08-03) |
| Disposition | Local hierarchical route **verified**; HTTP client often **unavailable** without deps/server |

---

## 14. Next steps

| Goal | Go to |
| --- | --- |
| Logic validation / prover / typed authority | [LOGIC_AND_PROOF_WORKFLOW.md](LOGIC_AND_PROOF_WORKFLOW.md) |
| MCP API domain reference | [MCP_AND_RUNTIME.md](../api/domains/MCP_AND_RUNTIME.md) |
| Server, tools, transports architecture | [mcp/README.md](../architecture/mcp/README.md) |
| First dataset offline path | [FIRST_DATASET_WORKFLOW.md](FIRST_DATASET_WORKFLOW.md) |
| Runtime entrypoints | [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |

---

## 15. Non-goals

- Requiring a live HTTP MCP server for the primary success path.
- Exhaustive tool catalog snapshots (live discovery is authority).
- Claiming hierarchical `logic_tools` zero-count as domain absence.
- Wallet/UCAN grant consumption or full NL→UCAN gates.
- Treating pipeline allow or tool list membership as proof or policy completion.
- P2P / gRPC / MCP++ multi-host deployment recipes.
