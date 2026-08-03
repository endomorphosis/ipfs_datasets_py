# MCP audit, event DAG, and observability

| Field | Value |
| --- | --- |
| Interface | `MCPObservabilityArchitecture@1` |
| Task | `IPFSDOC-052` |
| Status | `canonical` |
| Owner | architecture; mcp-security; operations |
| Source of truth | `ipfs_datasets_py/mcp_server/event_dag.py`; `cid_artifacts.py`; `policy_audit_log.py`; `audit_metrics_bridge.py`; `dispatch_pipeline.py` (`record_execution`); `metrics.py`; `monitoring.py`; `prometheus_exporter.py`; `otel_tracing.py`; `fastapi_service.py` (health/metrics routes); `p2p_service_manager.py`; `dag_compaction.py`; [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md); [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator, security reviewer |
| Related | [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md); [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md); Profile B CID artifacts |
| Review cadence | after audit schema, DAG, metrics name, or health-probe changes |

## 1. Purpose

This guide answers: **how MCP++ records content-addressed execution history
(event DAG / CID traces), how policy audit entries correlate with decisions and
receipts (including redaction), and how metrics, OpenTelemetry, Prometheus,
health/readiness, and P2P service states expose operational visibility —
without ever substituting for policy allow, proof, or successful dispatch.**

**Core inequality (repeatable):**

```text
  green metric  ≠  policy allow
  span OK       ≠  proof verified
  /health ready ≠  tool executed successfully
  audit "allow" ≠  one-time capability consumed
  receipt CID   ≠  Legal compliance
```

Visibility systems observe and correlate. They do not authorize.

## 2. Audience

| Audience | Use |
| --- | --- |
| **Operator / SRE** | Health, readiness, Prometheus scrape, P2P state interpretation |
| **Security / audit reviewer** | Correlate intent → decision → receipt; redaction expectations |
| **Developer / agent** | Attach EventDAG, audit log, OTel spans without inventing authority |
| **Architect** | Keep observability layers out of the authorization boolean |

## 3. Scope and non-goals

### In scope

- Profile B artifacts: intent, decision, receipt, execution envelope, event
  nodes
- Append-only Event DAG, walk/frontier/rollback, compaction tiers
- `PolicyAuditLog`, sinks, audit→Prometheus bridge
- Receipt correlation and redaction rules for logs/metrics
- `MetricsRegistry` / `EnhancedMetricsCollector`, Prometheus exporters,
  `/metrics`
- OpenTelemetry `MCPTracer` / `configure_tracing`
- `/health`, `/health/ready`, admin health, P2P `P2PServiceState`
- Explicit non-substitution rules for monitors vs policy/proof/dispatch

### Non-goals

- Full policy stage semantics — [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md)
- Transport parity matrix — [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md)
- Governed `DecisionReceipt@1` / capability consumption algebra —
  [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md)
- Operator start/stop runbook (IPFSDOC-053)

## 4. Mental model

```text
  Intent (intent_cid)
       │
       ▼
  Policy / pipeline DecisionObject (decision_cid)
       │                 │
       │                 └── PolicyAuditLog.record(policy_cid, intent_cid, decision, …)
       │                              │
       │                              └── optional AuditMetricsBridge → Prometheus
       ▼
  [if allowed] tool dispatch ──► output_cid
       │
       ▼
  ReceiptObject (receipt_cid)  links intent + decision + output
       │
       ▼
  EventNode(parents, intent_cid, decision_cid, receipt_cid, output_cid, …)
       │
       ▼
  EventDAG.append  ── hot tier ──► optional ZK/epoch compaction → cold tier
       │
       ├── OTel span attributes (category, tool, status)
       ├── request_id / correlation_id in result envelopes
       └── /metrics · /health · /health/ready · P2P state
```

Every CID edge is for **provenance and correlation**. Presence of a node or
counter increment does not grant a future call.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Event DAG structure and compaction hooks | Domain tool business metrics definitions |
| Policy audit buffer / JSONL sinks | External SIEM product configuration |
| MCP process metrics and HTTP health | Cluster-wide SLOs |
| P2P service state snapshots | Full libp2p stack internals |
| Redaction patterns for server error reporting | Full PII governance program |

**Inbound:** pipeline `record_execution`, policy evaluate paths, FastAPI ops
routes, monitoring loops.

**Outbound:** optional OTLP collectors, Prometheus scrapers, file audit JSONL,
cold-tier disk for compacted epochs.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| `EventNode` / artifacts | `cid_artifacts.py` | CID-linked intent/decision/receipt/output |
| `EventDAG` | `event_dag.py` | Append-only DAG, frontier, walk, rollback |
| `DAGCompactor` | `dag_compaction.py` | Epoch compaction when hot tier large |
| `DispatchPipeline.record_execution` | `dispatch_pipeline.py` | Build receipt + append event |
| `PolicyAuditLog` / `AuditEntry` | `policy_audit_log.py` | Structured evaluation trail |
| `AuditMetricsBridge` | `audit_metrics_bridge.py` | Audit sink → Prometheus tool-call counters |
| `MetricsRegistry` | `metrics.py` | mcppp_* counters/gauges/histograms |
| `EnhancedMetricsCollector` | `monitoring.py` | Tool, session, system, health registry |
| `PrometheusExporter` | `prometheus_exporter.py` | mcp_* export; no-op without client |
| `MCPTracer` | `otel_tracing.py` | Optional OTel spans for dispatches |
| FastAPI `/health`, `/health/ready`, `/metrics` | `fastapi_service.py` | Liveness, readiness, scrape text |
| `P2PServiceManager` / `P2PServiceState` | `p2p_service_manager.py` | Optional peer service lifecycle |

## 7. Event DAG and CID traces

### 7.1 Event node payload

Each `EventNode` is content-addressed (`event_cid`) and carries:

| Field | Purpose |
| --- | --- |
| `parents[]` | Causal predecessors (empty = root) |
| `intent_cid` | Planned action |
| `decision_cid` | Policy / pipeline verdict artifact |
| `receipt_cid` | Execution receipt |
| `output_cid` | Result payload identity |
| `interface_cid` / `proof_cid` | Optional interface and proof bundle |
| `peer_did` | Optional executing peer |
| timestamps | created / observed (ISO-8601 UTC) |

### 7.2 DAG operations

| Operation | Behavior |
| --- | --- |
| `append(node)` | Idempotent on CID; strict mode requires known parents |
| `get(cid)` | Fetch node |
| `frontier()` | Leaves (no children) — used as parents for next event |
| `walk(cid)` | Topological walk toward roots (provenance) |
| `rollback_to(cid)` | Identify nodes after a checkpoint (analysis / recovery aid) |

Properties:

- **Append-only** in normal operation (nodes not mutated in place).
- **Partial order:** disjoint parent sets → concurrent events.
- **Replay aid:** walk parents to reconstruct causal history (replay still
  requires inputs and side-effect policy; DAG alone is not re-execution).

### 7.3 Compaction and caps

| Mechanism | Detail |
| --- | --- |
| Hot tier soft threshold | `HOT_TIER_MAX` (~2000) triggers compaction attempts |
| Compaction | `DAGCompactor` moves older epochs to cold storage with Merkle-style proofs when available |
| Hard cap | ~10000 in-memory nodes; may evict oldest if compaction unavailable (logged as error) |

Compacted absence from hot memory **does not erase** cold-tier evidence when
compaction succeeded; treat eviction without cold storage as **integrity
degradation** and raise capacity/ops alarms.

### 7.4 Pipeline linkage

`DispatchPipeline.attach_event_dag(dag)` + `record_execution(intent, output,
error=...)`:

1. Builds `output_cid` from output payload when present.
2. Creates allow `DecisionObject` or error decision token.
3. Builds `ReceiptObject(intent_cid, output_cid, decision_cid)`.
4. Appends `EventNode` with parents from current frontier when DAG attached.

Hierarchical `dispatch_with_trace` may attach CID-native `_trace` / `trace`
envelopes on result dicts (Profile B) for client-visible provenance without
changing base MCP JSON-RPC formats.

### 7.5 Correlation keys

| Key | Where | Use |
| --- | --- | --- |
| `intent_cid` | Intent, decision, receipt, event, audit | Primary correlation spine |
| `decision_cid` / `policy_cid` | Decision + audit | Which policy produced the verdict |
| `receipt_cid` | Receipt + event | Post-execution attestation |
| `request_id` | Hierarchical dispatch result | Log correlation (not content-addressed) |
| `correlation_id` | Intent / receipt optional fields | Cross-system tracing glue |
| OTel span id | Tracer | Distributed trace join |

Always join on **CIDs for forensic authority** and use request/span IDs for
operational debugging. Do not treat request_id alone as an audit root of trust.

## 8. Audit log and receipt correlation

### 8.1 Policy audit entries

`PolicyAuditLog` (`policy_audit_log.py`) records optional evaluation rows:

| Field | Meaning |
| --- | --- |
| `timestamp` | Wall clock of record |
| `policy_cid` | Policy evaluated (or pipeline stage token) |
| `intent_cid` | Intent evaluated |
| `decision` | `allow` \| `deny` \| `allow_with_obligations` |
| `actor` / `tool` | Attribution |
| `justification` | Human-readable reason |
| `obligations` | Obligation type strings when present |
| `extra` | Caller metadata (must be redacted if sensitive) |

Design properties:

- **Zero overhead when disabled** (`enabled=False` or no singleton init).
- Thread-safe ring buffer (`max_entries`, default 10_000).
- Optional JSONL `log_path` append and custom `sink` callable.
- Process helper: `get_audit_log()`.

Pipeline metrics recorder and legacy stages may call `audit_log.record` with
synthetic `policy_cid` values such as `pipeline:<stage>` — useful for
operations, **weaker** than Profile D `policy_cid` content hashes.

### 8.2 Receipts vs audit rows vs governed receipts

| Artifact | Answers | Does **not** answer |
| --- | --- | --- |
| `AuditEntry` | What decision was logged for an evaluate | Whether the tool ran |
| `DecisionObject` | CID'd policy verdict | Side effects occurred |
| `ReceiptObject` | Immutable execution attestation (intent/decision/output) | Legal compliance or re-authorization |
| Governed `DecisionReceipt@1` | Side-effect-free authorization decision | MCP tool execution |

**Receipt presence does not mean a future call is allowed.** Execution
receipts are audit substrate for disputes, rollback analysis, and risk
analytics (`risk_score_from_dag`), not UCAN grants.

### 8.3 Redaction

| Surface | Redaction / sanitation |
| --- | --- |
| Server error reporting | Keys matching token/password/secret/auth/credential/api_key patterns redacted before external report (`server.py`) |
| Tool lifecycle note | Same secret-key patterns before external reporting ([TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md)) |
| Audit `extra` / params in CIDs | Prefer commitments over raw secrets; never log private keys or vault material |
| Metrics labels | Use category/tool/status enums — **not** free-form user content or tokens |
| OTel attributes | Bound low-cardinality attributes; do not attach raw params with PII |
| NL policy source | May be sensitive; store/access under operator policy; CID of source is not encryption |

Redaction protects confidentiality of **logs and exports**. It does not remove
the obligation to deny unauthorized access at the policy gate.

When exporting audit for incidents: correlate `intent_cid` → `decision_cid` →
`receipt_cid` → `event_cid`; scrub `extra`, param dumps, and peer auth tokens
before external disclosure.

## 9. Metrics

### 9.1 MCP++ `MetricsRegistry` (`metrics.py`)

Prometheus-text capable registry (stdlib implementation; optional
`prometheus_client` path elsewhere):

| Metric | Type | Meaning |
| --- | --- | --- |
| `mcppp_requests_total{method,status}` | Counter | Request volume |
| `mcppp_request_duration_seconds{method}` | Histogram | Latency |
| `mcppp_dag_events_total` | Gauge | DAG events (hot + compacted view) |
| `mcppp_dag_hot_events` | Gauge | In-memory hot tier size |
| `mcppp_dag_compaction_epochs_total` | Gauge | Compacted epochs |
| `mcppp_p2p_peers_connected` | Gauge | Connected peers |
| `mcppp_p2p_messages_total{direction}` | Counter | P2P traffic |
| `mcppp_ucan_delegations_total` | Gauge | Registered delegations |
| `mcppp_ucan_revocations_total` | Gauge | Revocations |
| `mcppp_rate_limit_rejected_total` | Counter | Rate-limit rejects |
| `mcppp_uptime_seconds` | Gauge | Process uptime |

### 9.2 Enhanced collector (`monitoring.py`)

`EnhancedMetricsCollector` tracks:

- Request counts, error counts, response times, active requests
- Per-tool call/error/latency/success rates
- Session metrics
- System snapshots (CPU/memory/disk when `psutil` available)
- Registered health check callables and results
- Alert thresholds (CPU, memory, disk, error rate, response time)
- Optional delegation metrics sampling via `record_delegation_metrics`

Disabled collector (`enabled=False`) records nothing — useful in tests.

### 9.3 Prometheus exporter (`prometheus_exporter.py`)

Bridges collector → Prometheus names such as:

- `mcp_tool_calls_total{category,tool,status}`
- `mcp_tool_latency_seconds{category,tool}`
- `mcp_active_connections`, `mcp_error_rate`
- `mcp_cache_hits_total` / `mcp_cache_misses_total`
- `mcp_system_cpu_usage_percent` / `mcp_system_memory_usage_percent`
- `mcp_uptime_seconds`

Without `prometheus_client`, metrics are **no-op stubs** (calls safe; scrape
may still use FastAPI text endpoint).

`AuditMetricsBridge` maps audit decisions to exporter tool-call counters with
`category="policy"` and status `allowed` / `denied`.

### 9.4 HTTP `/metrics`

`GET /metrics` on the FastAPI app emits simple Prometheus-compatible text
(uptime, requests, errors, active requests, avg latency, CPU/memory when
available). Scrape success proves the process answered HTTP — **not** that
policy or tools are correct.

### 9.5 Pipeline stage metrics

`PipelineMetricsRecorder` aggregates stage executions, skips, denials, average
durations, and per-tool allow/deny counts. Useful for tuning which gates fire;
**not** an allow list.

## 10. OpenTelemetry

Module: `otel_tracing.py`.

| API | Role |
| --- | --- |
| `configure_tracing(service_name, otlp_endpoint, export_protocol=...)` | Global TracerProvider + OTLP gRPC/HTTP exporter when packages installed |
| `MCPTracer.start_dispatch_span(category, tool, attrs)` | Span around hierarchical dispatch |
| `set_span_ok` / exception recording | Status on span |
| `@trace_tool_call` | Decorator helper |

When `opentelemetry-api` / SDK / exporters are missing, spans are **no-op**.
Missing traces must not fail closed into invented success, and present traces
must not be required for authorization.

Recommended attributes: tool category/name, `request_id`, allow/deny status,
intent/decision CIDs (not raw secrets). Join traces to the event DAG via
shared correlation fields when both are enabled.

## 11. Health and readiness

### 11.1 Liveness — `GET /health`

Returns HTTP 200 with `status: healthy`, timestamp, version, `uptime_seconds`
as long as the process can serve the route. **Liveness ≠ policy ready ≠ tools
correct.**

### 11.2 Readiness — `GET /health/ready`

Checks (representative):

| Check | OK meaning |
| --- | --- |
| Metrics collector importable / alive | Observability subsystem present |
| Tool manager discoverable categories | Hierarchical manager works; zero categories → warning |

HTTP **200** when checks pass, **503** when not — for load-balancer rotation.

Readiness does **not** assert:

- UCAN store loaded
- Temporal policies registered
- Event DAG durable
- Downstream IPFS / vector backends healthy
- Every tool importable

### 11.3 Admin / detailed health

`GET /admin/health` (rate-limited) may call monitoring tools for richer
component status. Treat as operator diagnostics.

### 11.4 Collector health checks

`EnhancedMetricsCollector` supports registered component health callables
producing `HealthCheckResult` (`healthy` | `warning` | `critical` |
`unknown`). Background loop samples system metrics and alerts on thresholds.

## 12. P2P service states

`P2PServiceManager` integrates optional Trio/libp2p task-queue and MCP++ peer
features alongside stdio/HTTP. State snapshot:

| Field (`P2PServiceState`) | Meaning |
| --- | --- |
| `running` | Service thread/lifecycle active |
| `peer_id` | Local peer identity when known |
| `listen_port` | Listen port if configured |
| `started_at` | Start timestamp |
| `last_error` | Last failure string |
| `workflow_scheduler_available` | MCP++ workflow scheduler present |
| `peer_registry_available` | Peer registry present |
| `bootstrap_available` | Bootstrap subsystem present |
| `connected_peers` | Count of connected peers |
| `active_workflows` | Active distributed workflows |

Degradation rules:

- P2P is **optional**; construction failures log and leave the subsystem unset
  rather than aborting the whole MCP server.
- `running=false` with empty `last_error` may mean disabled — not necessarily
  a security incident.
- Peer connectivity metrics never authorize a tool; Profile E carriage still
  lands on the same hierarchical dispatch and optional pipeline.

Monitoring may surface peer discovery / workflow failure-rate alerts (threshold
based). Alerts drive ops response; they do not flip pipeline allow.

## 13. Non-substitution (mandatory reading)

| Signal | Valid use | Invalid use |
| --- | --- | --- |
| Prometheus counter increase | Capacity / error-rate ops | Grant tool invoke |
| OTel span status OK | Latency / dependency debug | Prove policy allow |
| `/health` 200 | Process liveness | Claim compliance |
| `/health/ready` 200 | Accept traffic | Skip UCAN or temporal policy |
| Audit row `decision=allow` | Forensic trail | Replay as capability |
| Event DAG node present | Provenance / correlation | Re-authorize or invent proof |
| Receipt CID | Attest a past execution | Allow a new execution |
| P2P peers connected | Network health | Trust arbitrary peer intents |
| Risk score from DAG | Analytics / prioritization | Replace hard policy deny |

**Monitoring and visibility never substitute for policy, proof, or successful
dispatch.** Compose:

1. **Policy / UCAN / temporal / compliance / risk gates** for pre-dispatch
   allow/deny ([POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md)).
2. **Proof / governed authorization** when required by product authority
   ([GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md)).
3. **Dispatch** only after gates the host requires have passed.
4. **Observability** to record, alert, and investigate — always after or
   alongside, never instead of, the above.

## 14. End-to-end flows

### 14.1 Happy path with full observability

1. Host builds `PipelineIntent` → `intent_cid`.
2. Pipeline stages allow; `DecisionObject` / audit record `allow`.
3. Tool executes; output normalized.
4. `record_execution` → `ReceiptObject` + `EventNode` on DAG.
5. Metrics: tool success + latency; OTel span OK.
6. Client may see `request_id` and optional `_trace` CIDs.

### 14.2 Deny path

1. Stage denies (e.g. prohibition clause or risk above threshold).
2. Tool **not** executed; error returned.
3. Audit/metrics record **deny**; optional decision CID still correlatable.
4. No success receipt for tool output (hosts may still log the deny decision).
5. Monitors show increased deny/error rates — ops investigate; do not auto-allow.

### 14.3 Soft-skip path

1. Stage enabled but subsystem missing → stage passes with skip reason.
2. Execution may proceed if remaining stages allow.
3. Metrics show skips; **audit must not be read as “policy certified.”**
4. Production hosts should alarm on unexpected skip rates.

## 15. Failure modes and discrepancies

| Observation | Guidance |
| --- | --- |
| Dual metric namespaces (`mcp_*` vs `mcppp_*`) | Both exist; scrapers should document which exporter is wired |
| OTel / prometheus_client optional | No-op stubs; absence is not fail-open authorization |
| Audit ring buffer eviction | Old entries drop from memory; configure JSONL path for durability |
| DAG hard-cap eviction | Integrity risk if cold tier unavailable |
| Synthetic pipeline `policy_cid` strings | Distinguish from content-addressed Profile D policies |
| Health ready without P2P | Expected when P2P disabled |

## 16. Extension checklist

1. Attach `EventDAG` when provenance is required; call `record_execution` after
   dispatch (success and failure paths as appropriate).
2. Enable `PolicyAuditLog` with durable `log_path` in production security
   contexts.
3. Bridge audit to Prometheus only with redacted labels.
4. Configure OTel exporters in the host process start path; keep attributes
   low-cardinality.
5. Use `/health` for liveness and `/health/ready` for traffic; add custom
   readiness checks for required policy stores if your deployment needs them.
6. Surface P2P state in runbooks without treating peer count as trust.
7. Never short-circuit policy because metrics are green.

## 17. Validation

```bash
test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md
test -s docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
rg -n 'risk|UCAN|deny|redact|event DAG|receipt|trace|metric|health' \
  docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md \
  docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md

# Optional smoke
python -c "from ipfs_datasets_py.mcp_server.event_dag import EventDAG; from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode; d=EventDAG(); print(d.append(EventNode(intent_cid='i1')))"
```

## 18. Related documents

| Document | Relationship |
| --- | --- |
| [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md) | Gates that produce decisions audited here |
| [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) | Dispatch envelopes, pipeline attach, request_id |
| [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md) | Profile B artifacts and transport ops surfaces |
| [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md) | Authorization receipts vs execution receipts |
| [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) | Error-reporting redaction note |
| IPFSDOC-053 (planned) | Operator runbook using these probes and metrics |
