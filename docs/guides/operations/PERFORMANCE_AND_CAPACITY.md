# Performance and Capacity Guide

| Field | Value |
| --- | --- |
| Interface | `PerformanceCapacityGuide@1` |
| Task | `IPFSDOC-062` |
| Status | `canonical` |
| Owner | operations; performance |
| Source of truth | `ipfs_datasets_py/mcp_server/configs.py`; `server_context.py`; `fastapi_service.py` (rate limits, body size, SSE, exec timeout); `hierarchical_tool_manager.py` (graceful shutdown, discovery cache); `monitoring.py` / `metrics.py` / `prometheus_exporter.py`; `benchmarks/*`; `docs/EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md`; [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md); [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md); [DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md) |
| Last verified | 2026-08-03 |
| Audience | operator, SRE, developer capacity planning |
| Related | [DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md); [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md); [PERFORMANCE_TUNING_GUIDE.md](../../PERFORMANCE_TUNING_GUIDE.md) (ontology pipeline depth); domain profiling under `docs/profiling/` |
| Review cadence | after timeout defaults, rate limits, cache TTLs, or benchmark suite changes |
| Goal | `IPFSDOC-G101` |

> **Scope:** resource and concurrency **limits**, **caches**, **profiling /
> benchmarks**, and how to separate **measured baselines** from **targets**.
> This page does not redefine deployment modes
> ([DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md)) or recovery
> playbooks ([DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md)).

**Label legend:**

| Label | Meaning |
| --- | --- |
| **Measured baseline** | Dated result from a named benchmark or capture |
| **Target** | SLO / planning goal — re-measure before treating as SLA |
| **Example** | Illustrative limit from manifests or docs |
| **Supported default** | Current code default |
| **Optional** | Applies only when feature/deps enabled |
| **Unsupported** | Do not cite as capacity proof |

**Non-substitution:**

```text
  low avg latency on microbench  ≠  production multi-tenant capacity
  green CPU graph                ≠  successful tool dispatch
  high cache hit rate            ≠  content identity / correctness
  K8s limit headroom             ≠  tool timeout adequacy
  rate limit not tripped         ≠  backend not overloaded
```

---

## 1. Purpose

| Question | Answer location |
| --- | --- |
| What timeouts and caps does the process enforce? | §3 |
| How do I size CPU/memory/replicas? | §4 |
| What caches exist and how do they fail? | §5 |
| How do I profile and run benchmarks? | §6–7 |
| What measured numbers exist in-tree? | §7 |
| What should I put on a dashboard? | §8 |

---

## 2. Capacity mental model

```text
  Client / LB
       │  concurrency, body size, rate limits
       v
  MCP HTTP or stdio carrier
       │  tool timeout, SSE caps, in-flight requests
       v
  Hierarchical dispatch / optional policy pipeline
       │  discovery caches, result caches
       v
  Domain tool  ──► optional backends (IPFS, vectors, graph, LLM, provers)
                       │
                       └── network RTT, model load, disk cache, GPU
```

Capacity is **multi-layer**. Raising only the outer HTTP timeout without
backend headroom moves failures from “fast 504” to “slow 504.”

---

## 3. Resource and concurrency limits (code defaults)

### 3.1 Timeouts — Supported defaults

| Concern | Default | Source | Notes |
| --- | --- | --- | --- |
| Config tool timeout | **60 s** | `Configs.tool_timeout` | YAML/config path |
| ServerContext tool timeout | **30.0 s** | `server_context.py` | Context default |
| MCP++ HTTP exec | **30 s** | `MCPPP_EXEC_TIMEOUT_S` | Override per host |
| P2P startup wait | **~2.0 s** | `p2p_startup_timeout_s` | Then continue without P2P |
| Graceful manager shutdown | **30.0 s** | `graceful_shutdown(timeout=…)` | Rejects new dispatch |
| Event DAG ZK (optional) | up to hundreds of seconds | `MCPPP_EVENT_DAG_ZK_TIMEOUT_SECONDS` | **Optional** heavy path |
| Compose health interval | 30s interval, 10s timeout, 3 retries, 40s start | `docker-compose.mcp.yml` | **Example** probe timing |
| K8s liveness example | period 10s, timeout 5s, failureThreshold 3 | `mcp-deployment.yaml` | **Example** |

**Target (planning, not measured SLA):** choose tool timeouts ≥ p95 backend
latency × safety factor, and set LB idle timeouts **above** tool timeout.

### 3.2 Payload and connection caps — Supported defaults

| Cap | Default | Env / location |
| --- | --- | --- |
| Max HTTP body | **10 MiB** | `MCPPP_MAX_BODY_BYTES` |
| Max SSE connections | **50** | `MCPPP_MAX_SSE_CONNECTIONS` |
| Rate-limit store entries | **50_000** keys (cleanup/clear path) | `fastapi_service` |
| Embeddings generate rate | **100 / 3600 s** per key | in-process table |
| Semantic search rate | **1000 / 3600 s** per key | in-process table |
| Admin routes rate | **50 / 3600 s** per key | in-process table |

These rate limits are **process-local**, not cluster-global. Multiple replicas
multiply effective budget unless an external gateway enforces quotas.

### 3.3 Config / category surface

| Setting | Default / sample | Impact |
| --- | --- | --- |
| `enabled_tool_categories` | dataset, ipfs, vector, graph, audit, security, provenance (+ sample YAML extras) | Smaller set → less import/discovery work |
| `p2p_enabled` | `False` | **Optional** concurrency & ports |
| `p2p_enable_cache` | `True` when P2P on | Shared TTL cache over P2P |
| Embedding batch `maxItems` (sample schema) | **100** texts | Request shaping **example** in `config/mcp_config.yaml` |

### 3.4 Kubernetes / container envelopes — Example only

From `deployments/kubernetes/mcp-deployment.yaml` (illustrative):

| Resource | Request | Limit |
| --- | --- | --- |
| CPU | 250m | 500m |
| Memory | 512Mi | 1Gi |
| Replicas | 3 | — |

**Unsupported claim:** “1Gi is enough for all embedding models.” Large models,
browser automation, and GraphRAG pipelines need **measured** footprints.

**Target starting points (re-measure on your hardware):**

| Workload class | Memory target order | Notes |
| --- | --- | --- |
| Meta-tools only / light HTTP | 512Mi–1Gi | Matches example envelope order |
| Embedding model in-process | 2–8Gi+ | Model-dependent |
| PDF + ontology batch | 2–4Gi+ | Batch size sensitive |
| Full optional stack + dashboard | size each container separately | Do not share one limit blindly |

---

## 4. Sizing method (operator procedure)

### 4.1 Steps

1. **Define the critical path** (e.g. hierarchical dispatch only vs embedding search vs extraction).
2. **Establish a measured baseline** on representative hardware (§7).
3. **Record concurrency** (clients, parallel tools, `dispatch_parallel` fan-out).
4. **Watch saturation signals** (§8): CPU, RSS, active requests, error rate, p95 latency, ready flaps.
5. **Change one knob** (replicas, timeout, batch size, cache TTL).
6. **Re-measure**; keep the prior config as rollback.

### 4.2 Concurrency guidelines

| Pattern | Guidance | Label |
| --- | --- | --- |
| Stdio single client | One client process; tool timeout bounds hang risk | **Supported** |
| HTTP multi-client | Bound with reverse-proxy concurrency + process rate limits | **Target** design |
| `dispatch_parallel` | Fan-out multiplies backend load; cap N in callers | **Supported** API — measure N |
| SSE streams | Hard cap `MCPPP_MAX_SSE_CONNECTIONS` | **Supported default** |
| Multi-replica K8s | Stateless HTTP preferred; sticky only if local state required | **Example** topology |

### 4.3 Vertical vs horizontal

| Scale out (replicas) when | Scale up (CPU/mem) when |
| --- | --- |
| CPU-bound request handling is even across pods | Single request needs large model memory |
| Ready probes stable under load | RSS approaches limit → OOMKilled |
| No shared in-process-only state required | Disk cache cold starts dominate |

In-process rate limits and caches **do not shard**. Prefer gateway limits and
shared Redis/CDN only when you intentionally add them (**optional** / out of
default tree unless configured).

---

## 5. Caches

### 5.1 Cache inventory

| Cache | Layer | Trust | Invalidation / notes |
| --- | --- | --- | --- |
| Hierarchical discovery / schema cache | MCP manager | Listing metadata only | Rebuild on process restart; first call colder |
| Tool result cache (when enabled) | MCP backend | Performance only | Default TTL order **300 s** cited in runbook — verify host config |
| IPLD / block caches | storage | Must not redefine CID identity | See storage architecture |
| `CacheManager` / content-validated API caches | application | Validate content when required | TTL/stale policies vary |
| Router backend instance cache | IPFS router | Connection reuse | Process lifetime |
| HuggingFace / model disk cache | external libs | Download acceleration | Disk growth operator concern |
| P2P shared TTL cache | **Optional** P2P | Cross-peer memoization | Off when P2P disabled |
| Prometheus / metrics aggregations | observability | Not authoritative for allow | Scrape interval **example** 10–15s in monitoring ConfigMap |

Authority: [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md).

### 5.2 Operator rules

1. **Cache hit ≠ correct answer** for trust-sensitive outputs.
2. Prefer **safe inspection** of `/cache/stats` (auth-gated HTTP) before flush.
3. Flush/warm procedures belong in change windows — see diagnostics guide.
4. Disk caches need volume size **targets** (example: monitor free space < 15%).
5. After config changes that alter tool semantics, **invalidate** or restart so
   stale results cannot outlive the change.

### 5.3 Optional cache endpoints

| Endpoint | Auth | Use |
| --- | --- | --- |
| `GET /cache/stats` | current user dependency | Inspect sizes/hits when implemented path is live |

Absence of the route on a minimal image is **degraded observability**, not a
product identity change.

---

## 6. Profiling

### 6.1 When to profile

| Symptom | First profile focus |
| --- | --- |
| High p95 on dispatch | Hierarchical manager cold vs warm path |
| Memory climb | Model load, batch sizes, cache unbounded growth |
| CPU pegged | Extraction/regex hotspots, embedding encode |
| Timeouts only under load | Queueing + backend RTT, not just tool code |

### 6.2 Supported techniques (local)

```bash
# Example: cProfile a focused script (adjust module path)
python -m cProfile -o /tmp/prof.out path/to/benchmark_or_script.py
# Then analyze with pstats or snakeviz (optional tooling)

# Example: run a repository benchmark module under pytest
pytest benchmarks/bench_hierarchical_dispatch.py -v
```

| Tool | Use | Label |
| --- | --- | --- |
| `time.perf_counter` benches in `benchmarks/` | Latency baselines | **Supported** suite pattern |
| `cProfile` / `py-spy` | Hot functions | **Optional** host tools |
| `memory_profiler` / RSS sampling | Leak / peak RSS | **Optional** |
| OTel traces (`otel_tracing`) | Distributed spans when exporter configured | **Optional** |
| `/metrics` + Prometheus | Continuous signals | **Supported** when HTTP metrics route present |

**Redaction:** never attach production payloads, tokens, or PII to shared
profiles. Prefer synthetic fixtures from `benchmarks/`.

### 6.3 Domain tuning depth

Ontology extraction quick wins and deeper pipeline advice:
[PERFORMANCE_TUNING_GUIDE.md](../../PERFORMANCE_TUNING_GUIDE.md) and
`docs/profiling/*`. Those pages may contain **targets** and experimental tips;
promote numbers here only when dated and re-runnable.

---

## 7. Benchmarks and measured baselines

### 7.1 Suite location

| Path | Role |
| --- | --- |
| `benchmarks/` | Runnable performance tests and suites |
| `benchmarks/BENCHMARK_SUITE_GUIDE.md` | Suite orientation |
| `docs/EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md` | Dated extraction baseline |
| `docs/profiling/*` | Analyses (verify dates) |

### 7.2 Representative benchmarks (inventory)

| Benchmark module | Measures | Label |
| --- | --- | --- |
| `bench_hierarchical_dispatch.py` | Warm/cold dispatch; invalid path; parallel fan-out | **Supported** microbench pattern |
| `bench_ontology_generator_extract_entities_10k.py` | Entity extraction on ~10k+ token docs | **Measured** path (see §7.3) |
| `bench_end_to_end_pipeline_performance.py` | Pipeline E2E | Re-run for environment |
| `bench_graphrag_suite.py` | GraphRAG-oriented | **Optional** deps heavy |
| `bench_p2p_connection_pool.py` | P2P pool | **Optional** feature |
| `bench_query_optimizer_*` | Optimizer components / load | Domain-specific |
| `bench_infer_relationships_scaling.py` | Relationship inference scaling | Domain-specific |

Always record: **git SHA**, **CPU model**, **Python version**, **extras
installed**, **concurrency**, **date**.

### 7.3 Measured baseline — entity extraction (dated)

Source: `docs/EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md`  
Benchmark: `benchmarks/bench_ontology_generator_extract_entities_10k.py`  
System note: Linux, Python 3.12+ (capture host).

| Context | Avg | Median | P95 | Max | Throughput (est.) |
| --- | --- | --- | --- | --- | --- |
| General window (DocumentWindow=0) | **176.33 ms** | 174.85 ms | 186.92 ms | 190.32 ms | ~5.7 extractions/s |
| Legal window (DocumentWindow=2) | **184.19 ms** | 182.32 ms | 194.07 ms | 198.36 ms | ~5.4 extractions/s |

Iterations: 20 (+ 3 warmup). Token count ~15k synthetic.

**Regression thresholds from that capture (targets for CI alert design):**

| Status | Threshold on average |
| --- | --- |
| Healthy | avg ≤ **200 ms** |
| Warning | avg > **220 ms** (~1.25× baseline) |
| Regression alert | avg > **250 ms** (~1.4× baseline) |

These thresholds are **targets derived from one measured baseline**, not a
multi-hardware SLA. Re-baseline after major dependency upgrades.

### 7.4 Hierarchical dispatch — how to measure (no universal published SLA)

```bash
pytest benchmarks/bench_hierarchical_dispatch.py -v
```

Capture warm vs cold dispatch and parallel N. Publish results into your ops
notebook with hardware tags before setting **targets**.

**Unsupported:** copying a single developer laptop number into multi-tenant
SLO without re-measurement.

### 7.5 Load testing guidance (example procedure)

1. Start HTTP server with production-like timeouts and resource limits.
2. Confirm `/health/ready` 200.
3. Drive discover + safe invoke only (avoid destructive tools).
4. Ramp concurrency 1 → N; stop at error rate or latency **target** breach.
5. Record max steady RPS, p95, CPU, RSS, and ready-probe success ratio.
6. Leave headroom **target** (example planning: 30–50% CPU headroom).

---

## 8. Logs and metrics for capacity

### 8.1 Metrics (HTTP `/metrics` when available)

Emitted text metrics (from `fastapi_service.prometheus_metrics`):

| Metric | Meaning |
| --- | --- |
| `mcp_uptime_seconds` | Process uptime |
| `mcp_requests_total` | Request count |
| `mcp_errors_total` | Error count |
| `mcp_active_requests` | In-flight |
| `mcp_avg_response_time_ms` | Average latency sample |
| `process_cpu_percent` | CPU % |
| `process_memory_percent` | Memory % |

Scrape **example** (monitoring ConfigMap): interval 10–15s; alerts for down,
CPU > 0.8 for 5m, memory > 0.9 of limit for 5m — **example** rules, tune per
site.

### 8.2 Capacity-oriented signals

| Signal | Healthy direction | Investigate when |
| --- | --- | --- |
| `mcp_active_requests` | Bounded | Climbs without bound under steady load |
| Error ratio `errors/total` | Near zero for critical paths | Sustained rise |
| Avg / histogram latency | Stable vs baseline | Step change after deploy |
| `/health/ready` success | ~100% of scrapes for in-service pods | Flapping |
| Container OOMKills | Zero | Any — raise limit or cut batch |
| Disk free on cache volumes | Above site target | Cache growth |

### 8.3 Logs

| Practice | Rationale |
| --- | --- |
| Structured fields: `request_id`, tool, category, status | Correlate with metrics |
| Sample slow requests above threshold | Avoid log storms |
| Never log secrets, raw vault, full auth headers | Security |
| Retain enough history for last change window | Rollback forensics |

Full observability architecture:
[AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md).

---

## 9. Tuning playbook (safe order)

Change **one** class at a time:

| Order | Knob | Risk if mis-set |
| --- | --- | --- |
| 1 | Fix backend availability / pool size | Timeouts mask root cause |
| 2 | Batch sizes / max entities | Memory cliffs |
| 3 | Caches (TTL, enable pattern cache) | Stale results |
| 4 | Timeouts (`MCPPP_EXEC_TIMEOUT_S`, tool_timeout) | Hung workers vs premature fail |
| 5 | Rate limits / gateway concurrency | Thundering herd or artificial starvation |
| 6 | Replicas / CPU limits | Cost; noisy neighbor |
| 7 | Optional accelerators (GPU, remote embed API) | Ops complexity |

Ontology-oriented micro-optimizations (pattern cache, stopword pre-lowercasing,
max_entities): see [PERFORMANCE_TUNING_GUIDE.md](../../PERFORMANCE_TUNING_GUIDE.md)
— treat claimed speedups there as **targets** until re-measured on your data.

---

## 10. Unavailable dependencies and performance

| Missing dependency | Performance/capacity effect | Correct posture |
| --- | --- | --- |
| Embedding model not downloaded | First-call multi-minute delay or fail | Pre-warm or fail fast; do not advertise RPS |
| IPFS daemon down | Pin/get latency → timeout | Feature degrade; core MCP may stay ready |
| Optional prover binary | Proof path unavailable | Fail closed on trust; no fake PROVED |
| Prometheus exporter libs missing | Metrics sparse | Operability degrade |
| Cold discovery (empty process) | First list/dispatch slower | Warm with discover on startup probe |

Readiness may stay **200** while a domain backend is down — capacity plans must
include **synthetic checks** for critical tools, not only `/health`.

---

## 11. Explicit unsupported capacity claims

| Claim | Why unsupported |
| --- | --- |
| Single global RPS number for “the product” | Many surfaces and optional stacks |
| Example K8s 500m CPU as certified max | Workload-dependent |
| In-process rate limits as multi-tenant fair share | Not cluster-aware |
| Cache hit rate as quality metric | Performance only |
| Baseline from 2026-02-24 without re-run after major upgrades | Stale evidence |

---

## 12. Related documents

| Doc | Role |
| --- | --- |
| [DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md) | Modes, probes, external services |
| [DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md) | Saturation and timeout failures |
| [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md) | Timeout quick table, start/stop |
| [EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md](../../EXTRACTION_PERFORMANCE_BASELINE_2026_02_24.md) | Dated measured baseline |
| [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md) | Cache trust boundaries |

---

## 13. Change log

| Date | Note |
| --- | --- |
| 2026-08-03 | Initial `PerformanceCapacityGuide@1` for IPFSDOC-062 / IPFSDOC-G101 |
