# IPFS Datasets MCP Server — MCP++ Alignment

This document describes how the IPFS Datasets MCP Server aligns with the MCP++ specification
for advanced peer-to-peer, delegation, and provenance features.

**Last Updated:** 2026-02-25  
**MCP++ Version:** v39 (sessions 1–84 complete)  
**Status:** ✅ Full alignment achieved

---

## Overview

MCP++ extends the base Model Context Protocol with:
- **UCAN delegation** — decentralized capability-based access control
- **Event DAG provenance** — content-addressed event lineage
- **P2P transport bindings** — PubSub-based peer communication
- **Compliance checking** — automated policy enforcement and backup management
- **Policy audit logging** — immutable audit trail for policy decisions
- **NL UCAN policy** — natural language to UCAN policy compilation

---

## Implemented Components

### UCAN Delegation (`ucan_delegation.py`)

Full UCAN delegation chain management with support for:
- `DelegationToken` — individual UCAN tokens with expiry, nonce, audience, capabilities
- `Capability` — `ability` + `resource` with wildcard (`*`) resource matching
- `DelegationManager` — persistent delegation store with IPFS-backed reload
- `MergeResult` — merge protocol with `keys()`, `values()`, `items()`, `__getitem__`, `__len__`
- `IPFSReloadResult` — pin reload result with `iter_succeeded()`, `iter_all()`, `as_dict()`, `__len__`

Key operations (v1–v39 complete):
```python
mgr = DelegationManager()
cid = mgr.add(token)                              # Add token → returns CID
active = list(mgr.active_tokens_by_actor("alice")) # All tokens where audience == "alice"
by_res = list(mgr.active_tokens_by_resource("*")) # Wildcard resource matching
merge_result = mgr.merge(other_manager)           # Merge two stores
mgr.revoke(cid)                                   # Revoke by CID
```

### NL UCAN Policy Compiler (`nl_ucan_policy.py`)

Natural language text → UCAN policy compilation:
```python
compiler = NLUCANPolicyCompiler()
results = compiler.compile_batch(["Only Alice may read dataset X"])
results_with_explain = compiler.compile_batch_with_explain(texts, fail_fast=False)
# Returns List[Tuple[result, explanation_str]]
```

### P2P Transport (`mcp_p2p_transport.py`)

PubSub message bus for P2P communication:
```python
bus = PubSubBus()
sid = bus.subscribe("topic", handler)      # → subscription ID
bus.publish("topic", {"msg": "hello"})
topics = bus.topics()                      # All active topics
count = bus.total_subscriptions()          # Total subscription count (SIDs, not unique handlers)
ranked = bus.topics_with_count()           # [(topic, count), ...] sorted by count desc
replaced = bus.resubscribe(old_h, new_h, topic=None)  # Replace handler in-place → count
topic_map = bus.topic_sid_map()            # {topic: sorted_sid_list}
```

### Compliance Checker (`compliance_checker.py`)

Automated compliance checking with backup management:
```python
checker = ComplianceChecker()
result = checker.check("/path/to/data")
summary = checker.backup_summary("/path/to/data")
bak_files = checker.list_bak_files("/path/to/data")
newest = checker.newest_backup_name("/path/to/data")  # basename or None
oldest = checker.oldest_backup_name("/path/to/data")  # basename or None
names = checker.backup_names("/path/to/data")         # list of basenames

# Merge compliance states
merge = ComplianceMergeResult(added=1, skipped_protected=0, skipped_duplicate=0)
d = merge.to_dict()                        # {"added", "skipped_protected", "skipped_duplicate", "total"}
m2 = ComplianceMergeResult.from_dict(d)   # classmethod; missing keys → 0; ignores "total" key
```

### Policy Audit Log (`policy_audit_log.py`)

Ring-buffer audit log with JSONL persistence:
```python
log = PolicyAuditLog(max_entries=1000)
log.record(policy_cid="Qm...", intent_cid="Qm...", decision="allow", actor="alice")
recent = log.recent(max_entries=10)
log.export_jsonl("/path/audit.jsonl")
total = log.import_jsonl("/path/audit.jsonl")  # Returns total processed (not capped)
```

### Event DAG (`event_dag.py`)

Content-addressed event lineage:
```python
dag = EventDAG()
cid = dag.add_event({"type": "dataset_load", "source": "...", "timestamp": "..."})
event = dag.get_event(cid)
lineage = dag.get_lineage(cid)  # Full ancestor chain
```

---

## Architecture Integration

```
MCP Client (Claude, etc.)
    │
    ▼ MCP protocol
FastMCP server (server.py)
    │
    ├── HierarchicalToolManager ─→ lazy-load 51 tool categories
    │
    ├── RuntimeRouter ──────────→ FastAPI | Trio dual-runtime
    │
    ├── UCAN Layer ─────────────→ ucan_delegation.py (access control)
    │
    ├── Event DAG ──────────────→ event_dag.py (provenance)
    │
    ├── PubSub Bus ─────────────→ mcp_p2p_transport.py (P2P messaging)
    │
    ├── Compliance ─────────────→ compliance_checker.py (policy enforcement)
    │
    └── Audit Log ──────────────→ policy_audit_log.py (immutable trail)
```

---

## Implementation Status (2026-02-25)

| Component | Sessions | Status |
|-----------|----------|--------|
| UCAN Delegation (DelegationManager) | v1–v39 | ✅ Complete |
| NL UCAN Policy Compiler | v1–v39 | ✅ Complete |
| P2P Transport (PubSubBus) | v1–v39 | ✅ Complete |
| Compliance Checker | v1–v39 | ✅ Complete |
| Policy Audit Log | v1–v39 | ✅ Complete |
| Event DAG | v1–v39 | ✅ Complete |
| I18N Policy Detection | v22–v30 | ✅ 20 languages (fr/es/de/en/pt/nl/it/ja/zh/ko/ar/sv/ru/el/tr/hi/pl/vi/th/id) |
| Dual-Runtime (FastAPI+Trio) | Phase 2 | ✅ Complete |
| anyio-first migration | Phase M/N | ✅ Complete |

---

## Integration with IPFS Kit Python

The server supports two integration methods with IPFS Kit Python:

1. **Direct Integration**: Import and use IPFS Kit Python functions directly
2. **MCP Client Integration**: Connect to an existing IPFS Kit Python MCP server

### Direct Integration

```python
from ipfs_datasets_py.mcp_server import start_server
start_server(host="0.0.0.0", port=8000)
```

### MCP Client Integration

```python
start_server(host="0.0.0.0", port=8000, ipfs_kit_mcp_url="http://localhost:8001")
```

---

## Directory Structure

```
ipfs_datasets_py/mcp_server/
├── server.py                   # Main FastMCP server
├── hierarchical_tool_manager.py  # Lazy tool registry (99% context reduction)
├── fastapi_service.py          # FastAPI REST runtime
├── trio_adapter.py             # Trio runtime adapter
├── trio_bridge.py              # Trio/asyncio bridge
├── runtime_router.py           # Dual-runtime dispatch
├── p2p_service_manager.py      # P2P integration manager
├── ucan_delegation.py          # MCP++ UCAN delegation
├── nl_ucan_policy.py           # MCP++ NL policy compiler
├── mcp_p2p_transport.py        # MCP++ P2P PubSub transport
├── compliance_checker.py       # MCP++ compliance checking
├── policy_audit_log.py         # MCP++ policy audit log
├── event_dag.py                # MCP++ event DAG provenance
├── tool_registry.py            # Tool discovery and registration
├── monitoring.py               # Metrics and observability
├── validators.py               # Input validation
├── exceptions.py               # 18 custom exception classes
└── tools/                      # 51 tool category directories
    ├── dataset_tools/
    ├── graph_tools/
    ├── logic_tools/
    ├── ... (48 more categories)
```
