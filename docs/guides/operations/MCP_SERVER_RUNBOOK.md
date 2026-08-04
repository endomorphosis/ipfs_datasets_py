# MCP Server Operator Runbook

| Field | Value |
| --- | --- |
| Interface | `MCPServerRunbook@1` |
| Task | `IPFSDOC-053` |
| Status | `canonical` |
| Owner | operations; mcp-server |
| Source of truth | `ipfs_datasets_py/mcp_server/__main__.py`; `server.py`; `simple_server.py`; `fastapi_service.py` (health/metrics); `hierarchical_tool_manager.py`; `configs.py`; `server_context.py`; [architecture/mcp/README.md](../../architecture/mcp/README.md); [SERVER_AND_DISPATCH.md](../../architecture/mcp/SERVER_AND_DISPATCH.md); [INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md); [POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md); [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md); [RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md) §8; [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |
| Last verified | 2026-08-03 |
| Audience | operator, SRE, developer, agent running local or self-hosted MCP |
| Related | [MCP architecture index](../../architecture/mcp/README.md); [MCP_SYSTEMD_SETUP.md](../MCP_SYSTEMD_SETUP.md) (host-specific example) |
| Review cadence | after server entrypoint, health route, or lifecycle changes |
| Goal | `IPFSDOC-G070` / `IPFSDOC-G072` |

> **Scope of this runbook:** safe **local** (and self-hosted) start → discover →
> capability-probe → invoke → inspect → stop → diagnose → recover for the MCP
> server. Architecture contracts live in `docs/architecture/mcp/*`. This page
> is procedure authority for operators; it does **not** redefine tool inventory
> or policy algebra.

**Non-substitution (mandatory):**

```text
  /health 200          ≠  policy allow
  /health/ready 200    ≠  every tool works
  tools_list_* success ≠  backend extras installed
  metrics scrape OK    ≠  successful dispatch
  audit "allow" row    ≠  one-time capability for a future call
```

---

## 1. Purpose and audience

| Audience | Use this runbook to |
| --- | --- |
| **Operator / SRE** | Bring a process up, prove liveness/readiness, exercise discovery, shut down cleanly, recover from degraded states |
| **Developer** | Local stdio/HTTP smoke before integrating a client |
| **Agent** | Follow labeled steps without inventing a second server architecture |

---

## 2. Server classes (read first)

Binding rule: [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md).

| Class | How you start it | Use for ops? | Notes |
| --- | --- | --- | --- |
| **Canonical** | `python -m ipfs_datasets_py.mcp_server` (stdio default) or `--http` | **Yes — preferred** | Full hierarchical meta-tools; FastMCP stdio or FastAPI HTTP |
| **Simple / standalone** | `start_simple_server` / `simple_server` module | Migration / missing FastMCP only | **Deprecated** as feature peer; incomplete protocol surface |
| **Compatibility** | `mcp_server/compat/*` shims | Host migration | Not a second product architecture |
| **Legacy** | `legacy_mcp_tools`, class registries, Flask simple HTTP | Historical | Do not extend for new work |
| **Optional** | P2P, MCP++ meta-tools, `DispatchPipeline`, Profile G | When configured | Absence must not redefine base contract |

**This runbook’s default path is the canonical server.** Simple/legacy steps
are called out only under degraded recovery.

---

## 3. Prerequisites

### 3.1 Environment

| Requirement | Check | If missing |
| --- | --- | --- |
| Python 3 environment with package importable | `python -c "import ipfs_datasets_py; print('ok')"` | Install editable/dev tree or wheel; fix `PYTHONPATH` |
| Canonical MCP stack (`mcp` / FastMCP) for real protocol | Import succeeds when constructing full server | Process may use stubs (tests) or fall to **simple** path — **not** production canonical |
| Optional ASGI stack for HTTP | `hypercorn[trio]` preferred, or `uvicorn` | HTTP mode exits with install hint; use stdio instead |
| Writable working directory | Process CWD and config paths | Config/policy file loads fail closed with clear error |
| Network bind permission (HTTP only) | Port free on chosen host | Change `--port` or free the port |

### 3.2 Recommended local defaults

| Setting | Default / recommended local value | Source |
| --- | --- | --- |
| Mode | **stdio** (VS Code / MCP clients) unless probing HTTP health | `__main__.py` |
| HTTP host | `127.0.0.1` (do not expose to WAN without auth/TLS plan) | CLI `--host` |
| HTTP port | `3002` | CLI `--port` default |
| Config tool timeout | `60` s (`Configs.tool_timeout`) | `configs.py` |
| Context default tool timeout | `30.0` s (`ServerConfig.tool_timeout_seconds`) | `server_context.py` |
| MCP++ exec timeout (HTTP helpers) | `MCPPP_EXEC_TIMEOUT_S` default `30` | env |
| P2P startup wait | `p2p_startup_timeout_s` ~ `2.0` s | `configs.py` |
| Graceful manager shutdown | `graceful_shutdown(timeout=30.0)` default | hierarchical manager |

### 3.3 Optional environment variables (operator-facing)

| Variable | Role | Degraded if unset |
| --- | --- | --- |
| `IPFS_POLICY_STORE_PATH` | Optional policy store path at server init | Policy store unset; pipeline stages soft-skip when unconfigured |
| `SECRET_KEY` | HTTP session/JWT material on FastAPI path | Dev fallback may apply; **set in non-dev** |
| `MCP_CORS_ORIGINS` / `MCP_ALLOWED_HOSTS` | HTTP CORS / host allowlist | Defaults favor localhost |
| `MCPPP_EXEC_TIMEOUT_S` | HTTP tool execution budget | 30s default |
| `MCPPP_MAX_BODY_BYTES` | ASGI body limit | ~10 MiB default |
| `MCPPP_ALLOW_UNSIGNED_DELEGATIONS` | Relaxes UCAN unsigned path when set | Default requires signed delegations when UCAN path active |
| `IPFS_DATASETS_PROFILE_G_DB` | Profile G persistence | In-memory / unavailable features as configured |
| `IPFS_DATASETS_SECRETS_VAULT_FILE` | Secrets vault file | Vault empty; do not invent secrets |
| OTel exporter env (standard OTEL_*) | Trace export | Spans no-op when packages missing |

Do **not** put tokens, private keys, or vault material into log aggregation or
chat transcripts. See §9 Redaction.

### 3.4 Operator skill bar

- Comfort with a terminal, process signals (`SIGINT` / `SIGTERM`), and `curl`
  for HTTP probes
- Ability to distinguish **liveness** vs **readiness** vs **dispatch success**
- For P2P / UCAN hosts: additional host-specific config (out of default local path)

---

## 4. Procedure map

```text
  [0] Prerequisites (§3)
        │
        v
  [1] START          → process running (stdio or HTTP)
        │
        v
  [2] DISCOVER       → categories / tools list responds
        │
        v
  [3] CAPABILITY PROBE / HEALTH  → liveness + readiness (+ optional metrics)
        │
        v
  [4] INVOKE         → tools_dispatch (or HTTP flat) with known-safe params
        │
        v
  [5] INSPECT        → logs, envelopes, /metrics, audit CIDs if enabled
        │
        v
  [6] STOP           → clean exit; no orphan listeners
        │
   on failure ──► [7] DIAGNOSE → [8] RECOVER
```

Each procedure below lists: **goal**, **prerequisites**, **steps**,
**expected state**, **timeouts**, **unavailable / degraded**, **redaction**.

---

## 5. START

### 5.1 Goal

Bring up the **canonical** MCP process so a client can speak the protocol
(stdio) or HTTP carriers can bind health/tools routes.

### 5.2 Prerequisites

§3 satisfied; prefer a dedicated terminal or supervisor unit for long-lived
HTTP. For stdio, the **MCP client** usually spawns the process.

### 5.3 Steps — stdio (canonical default)

```bash
# From a tree where the package imports
python -m ipfs_datasets_py.mcp_server
# equivalent:
python -m ipfs_datasets_py.mcp_server --stdio
```

Optional:

```bash
python -m ipfs_datasets_py.mcp_server --stdio --debug
python -m ipfs_datasets_py.mcp_server --stdio --config /path/to/config.yaml
```

Python API (same launcher):

```python
from ipfs_datasets_py.mcp_server import start_stdio_server
start_stdio_server()
```

### 5.4 Steps — HTTP (canonical)

```bash
python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002
```

With debug:

```bash
python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002 --debug
```

Host selection order for ASGI: **Hypercorn+Trio** → **uvicorn** → exit with
install guidance (stdio remains available as a separate invocation).

CLI / systemd wrappers (when installed on the host):

```bash
# When packaging exposes the CLI
ipfs-datasets mcp start
# Example unit (host-specific; see MCP_SYSTEMD_SETUP.md)
# systemctl start ipfs-datasets-mcp.service
```

### 5.5 Expected state after start

| Mode | Expected |
| --- | --- |
| Stdio | Process stays attached to client stdin/stdout; registers hierarchical meta-tools; optional extended policy/compliance tools if importable |
| HTTP | Listener on `host:port`; FastAPI app serves tool routes, `/health`, `/health/ready`, `/metrics` when those routes are present |
| Optional P2P | If enabled in config, P2P subsystem may start after tools register; failure **logs and continues** core server |
| Optional pipeline | Default construction has **no** `DispatchPipeline`; attach is host-specific |

### 5.6 Timeouts (start)

| Event | Budget |
| --- | --- |
| Import + construct | Usually seconds; hangs → check circular imports / broken `mcp` shadowing (`ipfs_kit_py`) |
| P2P attach | ~`p2p_startup_timeout_s` (often 2s); then continue without P2P |
| HTTP bind | Immediate OS error if port in use |

### 5.7 Unavailable / degraded (start)

| Condition | Behavior | Operator action |
| --- | --- | --- |
| `mcp` / FastMCP missing | Stub may allow class import; **real run fails closed** or falls to simple server paths | Install MCP deps; do **not** treat simple mode as full protocol |
| Hypercorn missing | uvicorn fallback | Install `hypercorn[trio]` if Trio HTTP required |
| Neither ASGI server | Exit non-zero with pip hint | Use `--stdio` or install server |
| Config file invalid | Configuration error + exit | Fix YAML / path |
| Policy store path bad | Policy store unset; log | Fix `IPFS_POLICY_STORE_PATH` if needed; core tools still start |

### 5.8 Redaction (start)

Do not paste full config files containing secrets into tickets. Prefer
redacted excerpts (host, port, feature flags only).

### 5.9 Explicit non-start paths

| Do **not** use for production-canonical ops | Why |
| --- | --- |
| `start_simple_server()` as default | Degraded / deprecated peer of full server |
| Bulk-registering every tool on FastMCP | Removed from canonical path; use hierarchical meta-tools |
| Starting dashboard-only processes and calling them “MCP protocol” | Different surface; may share ports historically |

---

## 6. DISCOVER

### 6.1 Goal

Confirm the hierarchical discovery surface lists categories and tools without
claiming every listed tool can execute domain backends.

### 6.2 Prerequisites

Canonical server started (§5). For pure in-process checks, a Python REPL with
the package importable is enough (manager can discover without a live client).

### 6.3 Steps — hierarchical meta-tools (canonical contract)

Discovery order:

1. `tools_list_categories`
2. `tools_list_tools(category)`
3. `tools_get_schema(category, tool)` (optional before invoke)

In-process smoke (no MCP client required):

```python
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    tools_list_categories,
    tools_list_tools,
    tools_get_schema,
)

async def main():
    cats = await tools_list_categories(include_count=False)
    print(cats.get("status"), list(cats.get("categories", []))[:10])
    # Pick a category that exists on your tree; do not hard-code undated counts
    if cats.get("categories"):
        name = cats["categories"][0]["name"] if isinstance(cats["categories"][0], dict) else cats["categories"][0]
        tools = await tools_list_tools(name)
        print(tools.get("status"), tools)
    # Schema only after you know category + tool names from discovery

anyio.run(main)
```

CLI dynamic runner (when available):

```bash
ipfs-datasets tools categories
# then list tools for one category returned above
```

HTTP: use the host’s MCP/tools list routes or flat hierarchical descriptors
(`category.tool` views). Flat lists are **projections**, not a second registry.

### 6.4 Expected state

| Signal | Meaning |
| --- | --- |
| `status: success` on list categories | Manager scanned `mcp_server/tools/` directories |
| Non-empty categories | At least one category directory present |
| List tools for a category | Lazy import of that category succeeded for listed modules |
| Schema dict | Signature/docstring metadata available for that tool |

**Discovery listing a name does not guarantee capability success.**

### 6.5 Timeouts (discover)

| Call | Notes |
| --- | --- |
| List categories | Cheap directory scan; should complete in well under tool timeout |
| List tools | First call may import modules (slow if heavy optional deps); failures skip modules with warnings |
| Get schema | First call builds + caches; later O(1) |

Budget: stay within host tool timeout (30–60s defaults); if a single category
import hangs, treat as diagnose (§11), not “empty product.”

### 6.6 Unavailable / degraded (discover)

| Condition | Behavior |
| --- | --- |
| Optional tool module import fails | Module tools absent from that process’s list; warning log |
| Unknown category | Error envelope with `available_categories` |
| Simple/legacy server | May expose a different or reduced tool set — **do not** compare counts to canonical as architecture truth |
| Zero categories | Readiness may warn; treat as mis-install or wrong `tools` root |

### 6.7 Redaction (discover)

Schemas may describe parameters; do not fill schemas with real secrets when
logging discovery results. Log **names** and types, not production values.

---

## 7. CAPABILITY PROBE / HEALTH

### 7.1 Goal

Separate **process liveness**, **traffic readiness**, and **capability smoke**
from **authorization** and **full domain success**.

### 7.2 Prerequisites

HTTP mode for `/health` routes. Stdio-only deployments use process presence +
meta-tool discovery as the primary probe (no HTTP health unless a side HTTP
host is running).

### 7.3 Steps — health probes (HTTP)

```bash
HOST=127.0.0.1
PORT=3002

# Liveness
curl -sS -m 5 "http://${HOST}:${PORT}/health" | python -m json.tool

# Readiness (may 503 when not ready)
curl -sS -m 5 -w "\nHTTP %{http_code}\n" "http://${HOST}:${PORT}/health/ready" | python -m json.tool

# Metrics scrape (process answered HTTP ≠ tools correct)
curl -sS -m 5 "http://${HOST}:${PORT}/metrics" | head -n 40

# Optional admin detail (rate-limited; operator diagnostics only)
curl -sS -m 10 "http://${HOST}:${PORT}/admin/health" | python -m json.tool
```

### 7.4 Steps — capability probe (protocol-level)

After discover (§6), probe **schema** for one low-risk tool, then a **bounded**
invoke (§8) only if safe.

```text
tools_list_categories  →  tools_list_tools(cat)  →  tools_get_schema(cat, tool)
```

Optional: confirm extended meta-tools (`policy_*`, `compliance_*`) only if your
host registered them; their absence is **not** a start failure.

### 7.5 Expected state

| Probe | OK meaning | Not OK meaning |
| --- | --- | --- |
| `GET /health` → **200**, `status: healthy` | Process can serve the route; uptime/version present | Process down, wrong port, or reverse-proxy misroute |
| `GET /health/ready` → **200** | Metrics collector + tool manager discovery checks pass | **503** — do not send production traffic yet |
| `GET /health/ready` checks | Collector importable; categories discoverable | Zero categories → warning / not ready |
| `GET /metrics` text | Scrape endpoint responded | Missing metrics packages may still yield simple text or stubs |
| Schema probe success | Tool addressable | Does not prove backend engines |

Readiness does **not** assert: UCAN store loaded, temporal policies registered,
event DAG durable, IPFS/vector backends healthy, every tool importable.

### 7.6 Timeouts (probe)

| Probe | Suggested curl max-time |
| --- | --- |
| `/health` | 5s |
| `/health/ready` | 5–10s |
| `/metrics` | 5s |
| `/admin/health` | 10–30s (may call richer checks) |
| Meta-tool list/schema | Within tool timeout (30–60s) |

### 7.7 Unavailable / degraded (probe)

| Condition | Behavior | Action |
| --- | --- | --- |
| Stdio-only | No `/health` | Use process supervision + discover/invoke |
| Readiness 503 | Out of load balancer | Diagnose tool manager / collector; do not force traffic |
| Metrics no-op stubs | Counters absent | Optional; not a security fail-open |
| P2P `running=false` | Optional subsystem off or failed | Core stdio/HTTP may still be healthy |

### 7.8 Redaction (probe)

Health JSON is usually safe. Admin health and metrics labels must not include
raw tokens, passwords, or full tool params. Scrub before external tickets.

---

## 8. INVOKE

### 8.1 Goal

Execute one hierarchical tool via `tools_dispatch` (or HTTP flat projection)
with **known-safe** parameters and observe a structured result envelope.

### 8.2 Prerequisites

- Discover + schema probe succeeded for the chosen `(category, tool)`
- Understand side effects (writes, network, IPFS, legal scrapers) **before**
  calling; prefer read-only or local fixtures for first smoke
- If a `DispatchPipeline` is attached, expect **non-execution** on deny

### 8.3 Steps

In-process:

```python
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import tools_dispatch

async def main():
    result = await tools_dispatch(
        category="dataset_tools",   # replace with a category from live discover
        tool="load_dataset",        # replace with a tool from live discover
        params={"source": "squad", "format": "json"},  # example only — validate schema first
    )
    print(result)

anyio.run(main)
```

CLI (when available):

```bash
ipfs-datasets tools run <category> <tool> --params '{"key":"value"}'
```

HTTP flat form (when host exposes it): dispatch `category.tool` with JSON args
→ same hierarchical manager path.

### 8.4 Expected state

| Field / outcome | Meaning |
| --- | --- |
| `status: success` (+ domain fields) | Tool body ran and returned success-shaped dict |
| `status: error` + `error` message | Structured failure (not necessarily process crash) |
| `request_id` | Correlation for logs / traces |
| `available_categories` / `available_tools` | Address wrong; re-discover |
| Pipeline deny error without domain side effects | Gate blocked execution (expected when configured) |
| `_cached: true` | Result cache hit (only if tool metadata set `cache_ttl`) |

### 8.5 Timeouts (invoke)

| Layer | Typical budget |
| --- | --- |
| Default `Configs.tool_timeout` | 60s |
| `ServerConfig.tool_timeout_seconds` | 30s |
| Tool metadata `timeout_seconds` | Often 30s hint |
| `MCPPP_EXEC_TIMEOUT_S` (HTTP helpers) | 30s default |
| Peer/libp2p invoke | Often ~30s cancel scope |

On timeout: expect structured error or raised timeout — **never** silent partial
success presented as full success.

### 8.6 Unavailable / degraded (invoke)

| Condition | Typical response |
| --- | --- |
| Unknown category/tool | `status=error` + available_* hints |
| Optional backend missing inside tool | Error message (“unavailable”, ImportError, …); name may still list |
| Server shutting down | Reject new calls |
| Circuit breaker OPEN (if host wraps) | Error with `circuit_state` without invoke |
| Simple/legacy server | Different semantics — validate against that surface only |
| Policy stage soft-skip (missing subsystem) | Not a positive security decision; may still execute |

### 8.7 Redaction (invoke)

- Never put production API keys, UCAN private material, or vault secrets in
  `params` logged to shared channels
- Prefer fixture data for smoke invokes
- When filing incidents, keep `request_id` / CIDs; scrub param dumps

---

## 9. INSPECT

### 9.1 Goal

Collect enough operational evidence to confirm behavior or hand off a ticket
**without** leaking secrets or over-claiming authority from green monitors.

### 9.2 Steps

| Source | How | Use for |
| --- | --- | --- |
| Process logs | terminal stderr, `journalctl -u …` if systemd | Startup errors, import warnings, P2P last_error |
| Result envelopes | client/stdout JSON | `status`, `request_id`, error strings |
| `/metrics` | `curl` | Latency/error counters, uptime |
| OTel | collector if configured | Span category/tool/status — not authorization |
| Event DAG / receipts | host-attached DAG APIs | Correlate `intent_cid` → `decision_cid` → `receipt_cid` |
| Policy audit log | JSONL sink if configured | Decision trail; scrub `extra` |
| P2P state | manager snapshot fields | `running`, `last_error`, peer counts |

Architecture detail:
[AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md).

### 9.3 Expected state

Inspection surfaces are **present and consistent** with the configured
optional subsystems. Missing OTel packages ⇒ no-op spans (OK). Missing audit
sink ⇒ no file (OK) unless policy required it.

### 9.4 Redaction (mandatory)

| Surface | Redact |
| --- | --- |
| Server error reporting | Keys matching token/password/secret/auth/credential/api_key patterns (server-side) |
| Audit `extra` / params | Prefer commitments; never private keys or vault material |
| Metrics labels | Category/tool/status enums — not free-form user content or tokens |
| OTel attributes | Low-cardinality only; no raw PII params |
| Tickets / chat | Strip Authorization headers, peer tokens, full config secrets |

Redaction protects **confidentiality of exports**. It does not replace deny at
the policy gate.

### 9.5 Timeouts (inspect)

Prefer short scrapes (5–15s). Large DAG exports or ZK compaction paths may
need longer budgets (separate Profile F tooling; not default local smoke).

---

## 10. STOP

### 10.1 Goal

End the process cleanly so ports free, optional P2P stops, and delegation state
can persist when configured.

### 10.2 Steps

| Mode | How |
| --- | --- |
| Stdio under MCP client | Client disconnect / stop; or send interrupt to the child |
| Foreground terminal | `Ctrl-C` (`KeyboardInterrupt` handled in `__main__`) |
| Systemd | `systemctl stop ipfs-datasets-mcp.service` or host wrapper `mcp stop` |
| Docker | `docker compose stop` / container stop with grace period |
| Programmatic manager | `await manager.graceful_shutdown(timeout=30.0)` — rejects new dispatches, clears caches |

Canonical server `finally` paths stop P2P and save `DelegationManager` state
when present.

### 10.3 Expected state after stop

| Check | Expected |
| --- | --- |
| Process | Exited (or service inactive) |
| HTTP port | Not listening (`ss -ltnp | grep <port>` empty) |
| New dispatches | N/A (process gone); mid-flight may abort with errors |
| Supervisor | Unit shows stopped/inactive without crash loop |

### 10.4 Timeouts (stop)

| Path | Budget |
| --- | --- |
| `graceful_shutdown` default | 30s |
| systemd `TimeoutStopSec` | Host-defined; allow ≥ tool timeout if in-flight work matters |
| Forced kill | Last resort after grace; may leave incomplete audit/receipts |

### 10.5 Unavailable / degraded (stop)

Hung ASGI worker: escalate to `SIGTERM` then `SIGKILL` only after grace.
Document PID and last logs. Prefer root-cause (§11) over kill loops.

### 10.6 Redaction (stop)

Stop events are low sensitivity; still avoid dumping full environment blocks
into public issues.

---

## 11. DIAGNOSE

### 11.1 Goal

Map symptoms to a **layer** (import, bind, discovery, policy, domain, optional
subsystem) without conflating monitoring with authorization.

### 11.2 Symptom → layer matrix

| Symptom | First checks | Likely layer |
| --- | --- | --- |
| Module import fails at start | `python -c "import ipfs_datasets_py.mcp_server"`; conflict with shadowed `mcp` | Packaging / deps |
| HTTP won't bind | `ss -ltnp | grep PORT`; firewall | Host network |
| `/health` down, process up | Wrong port/proxy | Routing |
| `/health` OK, `/health/ready` 503 | Categories empty? collector import? | Readiness subsystem |
| Discover empty | Wrong install path; tools tree missing | Install / tree |
| Tool listed, invoke error “unavailable” | Optional extra / engine import inside tool | Domain optional dep |
| Invoke denied without side effects | Pipeline/UCAN/temporal config | Policy (expected if gated) |
| Timeout only | Params/backend latency; raise budgets carefully | Timeout / capacity |
| Metrics empty | Optional prometheus packages | Observability optional |
| P2P errors, tools OK | Optional P2P | Degraded optional path |

### 11.3 Collect (minimum ticket kit)

1. Exact start command and mode (stdio vs HTTP)
2. Package version / git SHA if known
3. `/health` and `/health/ready` bodies + HTTP codes (HTTP mode)
4. One discover response (category names only)
5. One failing invoke envelope (`status`, `error`, `request_id`) with **redacted** params
6. Last 50–100 log lines with secrets scrubbed

### 11.4 Timeouts (diagnose)

Bound interactive diagnosis loops (e.g. 15–30 minutes) before escalating.
Repeated restart without evidence is not diagnosis.

### 11.5 Redaction (diagnose)

Same as §9. Prefer CIDs and request IDs over payload bodies.

---

## 12. RECOVER

### 12.1 Goal

Restore a known-good **canonical** operating state with the least invasive
change that matches the failure class.

### 12.2 Recovery playbooks

| Failure class | Recover steps | Expected result |
| --- | --- | --- |
| **Stale / hung process** | STOP (§10) → confirm port free → START (§5) → HEALTH probe (§7) | Liveness/readiness OK |
| **Port conflict** | Choose free `--port` or stop conflicting service | HTTP bind succeeds |
| **Missing MCP deps** | Install FastMCP/`mcp` stack for canonical; avoid promoting simple_server | Full stdio/HTTP path works |
| **ASGI missing** | `pip install 'hypercorn[trio]'` or `uvicorn`; or fall back to stdio | HTTP or intentional stdio |
| **Bad config** | Fix YAML / env; restart | No ConfigurationError |
| **Empty categories** | Verify install includes `ipfs_datasets_py/mcp_server/tools/`; reinstall package | Discover non-empty |
| **Optional tool unavailable** | Install domain extra **or** accept structured error; do not fake success | Clear error or restored tool |
| **Readiness 503** | Fix collector/tool manager issues; keep LB draining until 200 | Ready for traffic |
| **Policy denials** | Inspect audit/decision; adjust **authorized** policy config — never bypass by disabling all gates silently in prod without change control | Expected allow/deny behavior documented |
| **P2P degraded** | Clear `last_error`; fix multiaddr/deps; or leave P2P off | Core MCP continues |
| **Crash loop (systemd)** | `systemctl reset-failed`; inspect journal; fix root cause before enable | Stable active unit |
| **Accidental simple/legacy path** | Stop simple_server; start canonical module entry; re-discover | Hierarchical meta-tools present |

### 12.3 Recover verification checklist

After any recover action, re-run in order:

1. **START** (§5)
2. **HEALTH** probe if HTTP (§7)
3. **DISCOVER** (§6)
4. Bounded **INVOKE** (§8) with safe params
5. **INSPECT** logs for new errors (§9)

### 12.4 Timeouts (recover)

| Action | Budget |
| --- | --- |
| Single restart cycle | Minutes, not hours |
| Dependency install | Per environment policy |
| Data repair (DAG/policy store) | Escalation; not silent truncate in prod |

### 12.5 Unavailable / degraded acceptance

Some recoveries **accept degradation**:

- Run **stdio-only** when HTTP ASGI cannot be installed
- Run **without P2P / without pipeline** when optional extras fail
- Leave individual tools **unavailable** when domain extras are absent

Never “recover” by:

- Inventing tool success without execution
- Treating green metrics as policy allow
- Documenting simple_server as equal architecture authority
- Publishing secrets to clear a blocked vault path

### 12.6 Redaction (recover)

Recovery runbooks shared across teams must use redacted env examples
(`SECRET_KEY=***`, paths only).

---

## 13. Timeout reference (quick table)

| Concern | Typical value | Where |
| --- | --- | --- |
| HTTP CLI default port | 3002 | `__main__.py` |
| Config tool timeout | 60s | `Configs.tool_timeout` |
| ServerContext tool timeout | 30s | `ServerConfig.tool_timeout_seconds` |
| Metadata timeout hint | 30s | `ToolMetadata` |
| MCP++ HTTP exec | 30s | `MCPPP_EXEC_TIMEOUT_S` |
| P2P startup wait | ~2s | `p2p_startup_timeout_s` |
| Graceful shutdown | 30s | `graceful_shutdown` |
| curl health probes | 5–10s | this runbook |
| Result cache default TTL (backend) | 300s when caching enabled | result cache |
| Event DAG ZK (optional) | up to hundreds of seconds | env `MCPPP_EVENT_DAG_ZK_TIMEOUT_SECONDS` |

Hosts may enforce stricter budgets; contracts **hint**, carriers **enforce**.

---

## 14. Unavailable and degraded behavior (summary)

| Situation | Operator-visible behavior | Treat as |
| --- | --- | --- |
| Canonical start with full deps | Meta-tools + lazy tools | Normal |
| FastMCP missing | Fail closed on real MCP run; possible simple fallback | **Degraded** — fix deps |
| Hypercorn missing | uvicorn or stdio | Feature degrade OK if logged |
| Tool optional import fail | Missing from list or invoke error | Per-tool unavailable |
| Pipeline unconfigured | Pass-through (not a security proof) | Default |
| Pipeline deny | Error, no tool body | Expected security |
| Soft-skip missing policy subsystem | Stage skip reason; may still run | Soft degrade — not “certified allow” |
| `/health` OK only | Process live | Insufficient for traffic if ready fails |
| P2P down | Core tools continue | Optional degrade |
| Simple/standalone/legacy | Reduced or different surface | Compatibility only |

Full matrices: [INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md)
§12; [SERVER_AND_DISPATCH.md](../../architecture/mcp/SERVER_AND_DISPATCH.md) §10;
[TOOL_LIFECYCLE_AND_REGISTRIES.md](../../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md) §13.

---

## 15. Safety rules for local and shared hosts

1. Bind HTTP to `127.0.0.1` unless you have auth, TLS, and allowlisting.
2. Prefer fixture data for first invoke; avoid production credentials in smoke.
3. Do not disable UCAN/policy gates in shared environments without change control.
4. Do not scrape `/admin/health` from untrusted networks (rate-limited; richer data).
5. Keep simple_server and legacy paths out of “production MCP” runbooks except
   as labeled recovery footnotes.
6. Never substitute monitoring for policy, proof, or successful dispatch.

---

## 16. Related architecture leaves

| Need | Document |
| --- | --- |
| Architecture index | [architecture/mcp/README.md](../../architecture/mcp/README.md) |
| Start/dispatch internals | [SERVER_AND_DISPATCH.md](../../architecture/mcp/SERVER_AND_DISPATCH.md) |
| Tool tree / unavailable tools | [TOOL_LIFECYCLE_AND_REGISTRIES.md](../../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md) |
| Transports / timeouts / degrade | [INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md) |
| Policy non-execution | [POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md) |
| Health, metrics, redaction detail | [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md) |
| Packaging entry map | [RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md) |
| Canonical vs compat decision | [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |
| Host-specific systemd example | [MCP_SYSTEMD_SETUP.md](../MCP_SYSTEMD_SETUP.md) |

---

## 17. Validation

```bash
# Declared outputs present and non-empty
test -s docs/architecture/mcp/README.md
test -s docs/guides/operations/MCP_SERVER_RUNBOOK.md

# Required procedure vocabulary present
rg -n 'start|discover|probe|health|stop|recover|unavailable' \
  docs/guides/operations/MCP_SERVER_RUNBOOK.md

# Canonical vs simple/legacy distinction present
rg -n 'canonical|simple_server|legacy|degrad' \
  docs/guides/operations/MCP_SERVER_RUNBOOK.md

# Optional structural smoke (environment-dependent)
python -c "import ipfs_datasets_py; print('ok')"
```

---

## 18. Change control

| Change type | Update |
| --- | --- |
| New health route or probe semantics | This runbook §7 + observability leaf |
| New start flags / ports | This runbook §5 + RUNTIME_ENTRYPOINTS |
| Policy gate behavior | POLICY leaf first; runbook only for operator interpretation |
| Promoting simple/legacy to canonical | Requires ADR supersession — **not** a runbook-only edit |
