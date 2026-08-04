# Diagnostics and Recovery Guide

| Field | Value |
| --- | --- |
| Interface | `DiagnosticsRecoveryGuide@1` |
| Task | `IPFSDOC-062` |
| Status | `canonical` |
| Owner | operations; SRE |
| Source of truth | `ipfs_datasets_py/mcp_server/__main__.py`; `fastapi_service.py` (health/ready/metrics); `hierarchical_tool_manager.py`; `server.py` / P2P manager; `deployments/kubernetes/*`; docker compose healthchecks; [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md) §11–12; [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md); [DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md); [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md) |
| Last verified | 2026-08-03 |
| Audience | operator, SRE, on-call, developer triaging runtime failures |
| Related | architecture MCP transport/dispatch guides; security incident paths (IPFSDOC-G102) for trust breaches |
| Review cadence | after health check, failure-mode, or recovery procedure changes |
| Goal | `IPFSDOC-G101` |

> **Scope:** diagnose **unavailable dependencies**, **storage / network /
> partial-service failures**, perform **safe inspection** before mutation, and
> execute **restart / migration / rollback** with verification. MCP-local
> start/stop detail remains in [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md);
> this guide is the broader operations decision tree.

**Label legend:**

| Label | Meaning |
| --- | --- |
| **Supported** | Preferred recovery / inspection path |
| **Example** | Site-specific compose/K8s/systemd illustration |
| **Optional** | Only when feature enabled |
| **Unsupported** | Dangerous or non-authoritative “fix” |
| **Measured baseline** | Compare against dated performance evidence |
| **Target** | Recovery time / verification goal — not automatic |

**Non-substitution (mandatory):**

```text
  restart cleared the alert     ≠  root cause fixed
  /health 200                   ≠  domain backend healthy
  audit allow historical row    ≠  future call allowed
  deleted volume “fixed” disk   ≠  data intentionally discarded with approval
  metrics green                 ≠  policy or proof success
```

---

## 1. Purpose and decision flow

```text
  [1] DETECT   symptom (alert, user report, failed probe)
        │
        v
  [2] TRIAGE   layer: process | network | ready | deps | storage | policy | capacity
        │
        v
  [3] INSPECT  safe read-only collection (§4)  ──► evidence pack
        │
        v
  [4] CLASSIFY failure class (§5–7)
        │
        v
  [5] RECOVER  least invasive playbook (§8–10)
        │
        v
  [6] VERIFY   health → ready → discover → safe invoke → metrics (§11)
        │
        v
  [7] PREVENT  ticket: root cause, baseline delta, follow-up
```

**Target (planning):** complete triage + inspect within one on-call focus block
(example: 15–30 minutes) before uncontrolled restart loops.

---

## 2. Symptom → layer matrix

| Symptom | First safe checks | Likely layer |
| --- | --- | --- |
| Process not running | supervisor/docker/k8s status; exit code; last logs | Lifecycle |
| Port not listening | `ss -ltnp`; correct `--port` / Service | Bind / network |
| `/health` fails | process up? proxy path? TLS terminate? | Liveness / routing |
| `/health` ok, `/health/ready` **503** | ready body `checks`; category count; metrics collector | Readiness subsystem |
| Discover empty / sparse | install tree; import errors in logs | Packaging / optional imports |
| Tool listed, invoke “unavailable” | domain extra, binary, env | Optional dependency |
| Widespread timeouts | backend RTT, CPU throttle, timeout knobs | Capacity / network |
| Only one replica bad | node pressure, volume, image pull | Partial service |
| 401/403 on tools | auth token, policy pipeline, UCAN | AuthZ (may be correct deny) |
| 429 rate limited | client budget; in-process tables | Concurrency limits |
| OOMKilled / exit 137 | memory limit vs model/batch | Capacity |
| Disk full | cache/IPFS/volume usage | Storage |
| Split behavior stdio vs HTTP | different entry path or image | Configuration drift |
| P2P errors, core tools OK | optional P2P | Optional degrade |

---

## 3. Failure classes (catalog)

### 3.1 Unavailable dependencies

| Dependency | Detection | Feature impact | Trust impact |
| --- | --- | --- | --- |
| FastMCP / `mcp` stack | start fails or simple fallback | Canonical protocol reduced | Do not claim full MCP parity |
| ASGI (Hypercorn/uvicorn) | HTTP start exit with pip hint | HTTP surface down; stdio may work | Availability only |
| IPFS daemon / kit | tool errors; pin/get fail | IPFS tools unavailable | No fake pin success |
| Embedding model / weights | import or runtime error; cold download hang | vector tools fail/slow | N/A |
| Graph DB | connection errors | graph tools fail | N/A |
| Prover binaries | proof path errors | proof unavailable | **Fail closed** — never invent PROVED |
| Policy store path | logs; soft-skip stages | weaker audit/policy | Not “certified allow” |
| OTel / Prometheus libs | empty scrape / no spans | observability gap | N/A |
| P2P stack | `last_error` / state | P2P off | Core may continue |

Policy: [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) —
degrade **features**; fail closed on **trust**.

### 3.2 Storage failures

| Failure | Signs | Safe first response |
| --- | --- | --- |
| Volume full | ENOSPC; write errors; IPFS repo stuck | Free space **or** expand volume; identify cache vs primary data |
| Permission denied | EACCES on state/cache paths | Fix ownership (non-root container user 1000 in K8s example); do not `chmod 777` as default |
| Corrupt DuckDB / state file | P2P or Profile G errors | Stop writers; **backup file**; restore known-good or reinitialize **with approval** |
| Lost emptyDir / ephemeral | state reset after reschedule | Expected for non-durable mounts; move to PVC if needed |
| Snapshot restore partial | mixed old/new CIDs or configs | Freeze traffic; complete restore; verify |

**Unsupported:** deleting unknown directories under `~/.cache` or cluster PVCs
without identifying contents and approval.

### 3.3 Network failures

| Failure | Signs | Response |
| --- | --- | --- |
| DNS to backend | getaddrinfo errors | Fix Service/DNS; temporary IP only as emergency |
| TCP timeout to IPFS/API | tool timeouts | Check network policies, published ports, firewall |
| TLS / proxy mismatch | 502/504 from ingress | Align ingress timeouts with tool timeout |
| Partial partition | intermittent multi-replica errors | Check mesh/CNI; drain bad nodes |
| Client uses wrong port | connection refused | Align module default **3002** vs compose **8000** |

### 3.4 Partial-service failures

| Pattern | Meaning | Action |
| --- | --- | --- |
| 1 of N pods not ready | instance-local fault | `kubectl describe` / logs; restart that pod; keep traffic on ready set |
| Dashboard down, MCP up | UI-only | Repair dashboard; API clients unaffected |
| IPFS down, MCP ready 200 | optional backend | Mark IPFS tools degraded; fix Kubo; synthetic tool check |
| Policy denies only some tools | expected security | Do not “fix” by disabling policy without change control |
| Metrics absent, tools work | observability degrade | Restore exporter; not a dispatch emergency |
| Simple/standalone process serving prod traffic | **unsupported** peer architecture | Migrate to canonical module entry ([ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md)) |

---

## 4. Safe inspection (read before write)

### 4.1 Principles

1. **Prefer read-only** commands until the failure class is known.
2. **Redact** secrets, tokens, vault material, raw PII from tickets.
3. Capture a **minimum evidence pack** before restart when possible (restart
   destroys volatile state).
4. Do not run destructive tools (delete pins, drop DBs, mass unpin) during
   triage without explicit approval and rollback plan.

### 4.2 Minimum evidence pack

| Item | Command / source | Redaction |
| --- | --- | --- |
| Start command & mode | process argv / compose service / K8s command | strip secrets |
| Version / SHA | package version, image tag, git SHA | — |
| Liveness | `curl -sS $BASE/health` | — |
| Readiness | `curl -sS $BASE/health/ready` | — |
| Metrics snapshot | `curl -sS $BASE/metrics` | — |
| Discover sample | category names only | no credentials |
| One failing envelope | `status`, `error`, `request_id` | redact params |
| Logs | last 50–100 lines | scrub tokens/env dumps |
| Resource events | `docker inspect` / `kubectl describe pod` | — |
| Disk | `df -h` on state/cache mounts | — |

### 4.3 Supported inspection commands (examples)

```bash
# Process / import
python -c "import ipfs_datasets_py; import ipfs_datasets_py.mcp_server; print('ok')"

# HTTP probes (adjust host/port)
BASE=http://127.0.0.1:3002
curl -sS --max-time 5 "$BASE/health"; echo
curl -sS --max-time 5 "$BASE/health/ready"; echo
curl -sS --max-time 5 "$BASE/metrics" | head -n 40

# Containers (example compose project)
docker compose -f docker/docker-compose.mcp.yml ps
docker compose -f docker/docker-compose.mcp.yml logs --tail=100 mcp-server

# Kubernetes (example namespace from sample manifests)
kubectl -n ipfs-datasets-mcp get pods,svc
kubectl -n ipfs-datasets-mcp describe pod -l app=mcp-server
kubectl -n ipfs-datasets-mcp logs -l app=mcp-server --tail=100

# Host ports
ss -ltnp | grep -E '3002|8000|8899' || true
```

### 4.4 Auth-gated inspection

| Endpoint | Use when | Caution |
| --- | --- | --- |
| `/admin/health` | deeper health | requires auth; rate limited |
| `/admin/stats` | system stats | requires auth |
| `/cache/stats` | cache view | requires auth; read-only prefer |
| `/mcp/dag/frontier` / history | Event DAG inspect | **Optional** MCP++ surfaces |
| Audit report routes | security correlation | redaction rules apply |

Prefer CIDs and request IDs over payload bodies in shared channels.

### 4.5 Stdio-only deployments

No `/health` HTTP surface unless a side server is running. Inspect via:

- Process supervisor state
- Client error messages
- In-process discover/invoke smoke (runbook)
- Log files configured on the host

---

## 5. Diagnose playbooks by class

### 5.1 Unavailable dependency

| Step | Action |
| --- | --- |
| 1 | Identify exact import/binary/URL error from logs |
| 2 | Classify: required for **canonical core** vs **optional tool** |
| 3 | If core (MCP stack): install deps; do not normalize on simple_server |
| 4 | If optional: document degrade; install extra **or** accept structured errors |
| 5 | Re-run discover + one tool that needs that dependency |
| 6 | Update runbook notes for this environment’s intentional absences |

### 5.2 Storage

| Step | Action |
| --- | --- |
| 1 | `df -h`; inode use; mount options |
| 2 | Identify which path (`MCPPP_STORAGE_DIR`, P2P queue, IPFS repo, HF cache) |
| 3 | If full: clear **known** disposable caches first; never wipe primary pinsets without approval |
| 4 | If corrupt: stop service; copy file aside; restore backup or reinit with ticket |
| 5 | Restart → verify ready → spot-check dependent tools |

### 5.3 Network

| Step | Action |
| --- | --- |
| 1 | From **same network namespace** as the process, curl health and backend |
| 2 | Compare published vs target ports (3002 vs 8000 drift) |
| 3 | Check NetworkPolicy / security groups / DNS |
| 4 | Align proxy `proxy-read-timeout` with `MCPPP_EXEC_TIMEOUT_S` / tool timeout |
| 5 | Retry with exponential backoff only after connectivity proven |

### 5.4 Partial service

| Step | Action |
| --- | --- |
| 1 | Map which components fail (server / dashboard / IPFS / single replica) |
| 2 | Ensure LB uses **readiness** (prefer `/health/ready`) not only liveness |
| 3 | Drain or delete bad pod; avoid simultaneous full restart unless necessary |
| 4 | If config drift between replicas: pin one ConfigMap revision |
| 5 | Verify majority Ready before closing incident |

### 5.5 Capacity / saturation

See [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md).

| Step | Action |
| --- | --- |
| 1 | Compare latency/errors to **measured baseline** if available |
| 2 | Check CPU throttle, RSS vs limit, `mcp_active_requests` |
| 3 | Look for 429s and body-too-large responses |
| 4 | Reduce concurrency or raise resources **one change at a time** |
| 5 | If OOM: lower batch/model size or raise memory limit |

### 5.6 Policy / authorization denials

| Step | Action |
| --- | --- |
| 1 | Confirm denial is unexpected (may be correct) |
| 2 | Collect decision/receipt/audit identifiers if present |
| 3 | Inspect policy store configuration — **no silent gate removal** |
| 4 | Escalate security owners for policy change |

---

## 6. Logs and metrics during incidents

| Source | Use |
| --- | --- |
| Process stdout / journald | Start failures, tracebacks |
| `docker compose logs` / `kubectl logs` | Containerized paths |
| `/metrics` | rates, errors, active requests, CPU/mem % |
| Prometheus alerts (example rules) | MCPServerDown, HighCPU, HighMemory |
| Event DAG / audit bridges | Correlation after stability restored |
| Dashboard status API | UI-path dependency only |

Alert expressions in `deployments/kubernetes/monitoring.yaml` are **examples**
— validate against your metrics backend.

---

## 7. Recovery playbooks

### 7.1 Restart (Supported)

| Scope | Procedure | When |
| --- | --- | --- |
| Local process | SIGINT/SIGTERM → confirm port free → start canonical module | Hung process, config reload |
| Compose | `docker compose … restart mcp-server` or `up -d` | Container unhealthy |
| Kubernetes | `kubectl rollout restart deploy/mcp-server` or delete pod | Pod-level fault |
| Systemd **example** | `systemctl restart …` after journal review | Host service |

After restart, always **verify** (§11). Graceful shutdown budget ~**30 s**
(manager default); forced `SIGKILL` is last resort (may lose in-flight audit).

### 7.2 Migration

| Migration | Steps | Risk |
| --- | --- | --- |
| Simple/standalone → canonical | Stop old; start `python -m ipfs_datasets_py.mcp_server`; re-discover hierarchical tools | Client config paths |
| Port 8000 ↔ 3002 | Update clients, probes, Services together | Split-brain clients |
| Ephemeral → durable volume | Stop; copy state; mount PVC/host path; start; verify | Data loss if skip copy |
| Enable IPFS sidecar | Add service; configure kit URL; synthetic pin/get | Optional only |
| Config schema change | Diff YAML; apply; rolling restart; watch ready | Invalid YAML → crash loop |

### 7.3 Rollback

| Failed change | Rollback action | Verify |
| --- | --- | --- |
| Bad image tag | Redeploy previous **digest** | ready + discover |
| Bad env/config | Restore prior ConfigMap/secret revision | ready + one invoke |
| Bad compose revision | `up` previous compose file + images | `ps` healthy |
| Failed K8s rollout | `kubectl rollout undo deploy/mcp-server` | rollout status |
| Aggressive timeout reduce | Restore prior `MCPPP_EXEC_TIMEOUT_S` / tool_timeout | error rate |
| Accidental policy bypass attempt | Re-enable gates from last known-good policy | intentional deny tests |

**Target:** know previous image digest **before** upgrading.

### 7.4 Recovery matrix (quick)

| Failure class | Recover | Expected |
| --- | --- | --- |
| Stale/hung process | STOP → START → HEALTH | Live + ready |
| Port conflict | Free port or change bind | Listen success |
| Missing MCP deps | Install canonical stack | Full protocol |
| Missing ASGI | Install server or use stdio | Intentional mode |
| Bad config | Fix YAML/env; restart | No ConfigurationError |
| Empty categories | Fix package data/`tools` tree | Discover non-empty |
| Optional tool down | Install extra or accept error | Clear status |
| Ready 503 | Fix collector/manager; keep drained | Ready 200 |
| Storage full | Free/expand; restart if needed | Writes succeed |
| Network to backend | Fix DNS/policy/proxy | Tool RTT normal |
| Partial replica fail | Replace pod; keep others | Majority ready |
| OOM | Resize or reduce load | No restart loop |
| Crash loop | reset-failed / backoff; fix root cause | Stable ready |
| P2P degraded | Fix or disable optional P2P | Core MCP OK |
| Wrong architecture peer | Migrate to canonical entry | Hierarchical tools |

---

## 8. Compose and Kubernetes recovery notes (Example)

### 8.1 Compose

```bash
# Example
docker compose -f docker/docker-compose.mcp.yml ps
docker compose -f docker/docker-compose.mcp.yml logs --tail=200 mcp-server
docker compose -f docker/docker-compose.mcp.yml restart mcp-server
# Full recreate (disruptive)
docker compose -f docker/docker-compose.mcp.yml up -d --force-recreate mcp-server
```

Dashboard depends on server health in the sample file — fix **mcp-server**
before chasing dashboard-only errors.

### 8.2 Kubernetes

```bash
# Example namespace from sample manifests
NS=ipfs-datasets-mcp
kubectl -n "$NS" get pods
kubectl -n "$NS" rollout status deploy/mcp-server
kubectl -n "$NS" rollout undo deploy/mcp-server   # rollback
kubectl -n "$NS" delete pod -l app=mcp-server --field-selector=status.phase!=Running
```

Sample probes may use `/health` for both liveness and readiness — if ready
semantics matter, patch readiness to `/health/ready` when the image serves it
([DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md) §6).

---

## 9. Data repair and dangerous operations

| Operation | Approval | Preconditions | Rollback |
| --- | --- | --- | --- |
| Flush application caches | low–medium | inspect stats first | cold performance only |
| Delete P2P queue DB | medium | P2P drained; backup file | restore backup |
| Reinit Profile G DB | medium | export needed goals/tasks | restore file |
| IPFS `repo gc` | high | understand unpinned loss | from pins/backups only |
| PVC wipe | high | written destruction ticket | restore snapshot |
| Disable all policy gates | **unsupported** as silent recovery | security change control only | re-enable immediately |

When in doubt: **snapshot → inspect → limited repair → verify**.

---

## 10. Acceptable degraded modes

Document these as intentional when full restore is blocked:

| Mode | Allowed? | Communication |
| --- | --- | --- |
| Stdio-only without HTTP | Yes | No HTTP SLOs |
| HTTP without P2P | Yes | Optional path off |
| Core MCP without IPFS/graph/LLM | Yes | Per-tool unavailable |
| Metrics/OTel missing | Yes short-term | Operability risk |
| Simple/standalone as permanent prod | **No** | Migrate to canonical |
| Trust claims without provers | **No** | Fail closed |
| Serving with known secret placeholders | **No** | Rotate secrets |

---

## 11. Post-recovery verification checklist

Run in order after **any** recover action:

1. **Process / rollout** stable (no CrashLoopBackOff)
2. **`GET /health` → 200** (HTTP) or process alive (stdio)
3. **`GET /health/ready` → 200** when FastAPI ready route exists
4. **Discover** categories non-empty
5. **Safe invoke** of a known-benign tool or meta-tool
6. **Critical optional deps** synthetic check (IPFS/embed) if they are in SLO
7. **`/metrics`** scrape if monitoring required
8. **Error rate / latency** vs pre-incident or **measured baseline**
9. **Ticket update** with root cause, timeline, follow-ups

Cross-check detailed MCP steps:
[MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md) recover verification.

---

## 12. Escalation

| Condition | Escalate to |
| --- | --- |
| Suspected security breach / secret leak | Security owners; incident process (G102 docs) |
| Data loss risk on shared volumes | Storage owner + change board |
| Policy/authorization ambiguity | Policy owners; do not bypass |
| Repeated capacity incidents | Capacity planning; re-baseline benchmarks |
| Packaging/import architecture confusion | Maintainers; ADR-007 |

---

## 13. Related documents

| Doc | Role |
| --- | --- |
| [DEPLOYMENT_AND_RUNTIME.md](DEPLOYMENT_AND_RUNTIME.md) | Modes, persistence, probes |
| [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md) | Limits, caches, baselines |
| [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md) | MCP diagnose/recover detail |
| [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Feature degrade vs trust fail-closed |
| [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md) | Metrics/health semantics |

---

## 14. Change log

| Date | Note |
| --- | --- |
| 2026-08-03 | Initial `DiagnosticsRecoveryGuide@1` for IPFSDOC-062 / IPFSDOC-G101 |
