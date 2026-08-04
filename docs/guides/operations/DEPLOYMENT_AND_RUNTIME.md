# Deployment and Runtime Guide

| Field | Value |
| --- | --- |
| Interface | `DeploymentRuntimeGuide@1` |
| Task | `IPFSDOC-062` |
| Status | `canonical` |
| Owner | operations |
| Source of truth | `ipfs_datasets_py/mcp_server/__main__.py`; `configs.py`; `fastapi_service.py` (health/metrics); `docker/docker-compose.mcp.yml`; `docker/Dockerfile.mcp-minimal`; `ipfs_datasets_py/mcp_server/Dockerfile*`; `deployments/kubernetes/*`; `config/mcp_config.yaml`; [RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md); [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md); [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [ADR-002](../../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | operator, SRE, developer deploying local or self-hosted runtimes |
| Related | [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md); [DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md); [DOCKER_DEPLOYMENT_GUIDE.md](../../deployment/DOCKER_DEPLOYMENT_GUIDE.md) (historical/example depth); [MCP_SYSTEMD_SETUP.md](../MCP_SYSTEMD_SETUP.md) (host-specific example) |
| Review cadence | after entrypoint, Dockerfile, compose, or Kubernetes manifest changes |
| Goal | `IPFSDOC-G101` |

> **Scope:** how to **choose a deployment mode**, **configure** runtime surfaces,
> wire **persistence and external services**, and prove **health/readiness** —
> without claiming a universal “production certified” posture for every path in
> the tree. Architecture contracts live under `docs/architecture/*`. Process
> start/stop procedures for the MCP server live in
> [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md).

**Label legend (used throughout this guide and siblings):**

| Label | Meaning |
| --- | --- |
| **Supported** | Preferred current-tree path; maintain and document as primary |
| **Example** | Manifest, compose file, or host unit that illustrates a pattern; requires site-specific hardening before shared use |
| **Optional** | Feature works when deps/config are present; absence must not redefine the base contract |
| **Unsupported** | Do not treat as equal architecture authority; migration/compat only |
| **Measured baseline** | Dated measurement from benchmarks or captured evidence |
| **Target** | Operational goal / SLO intent — not a guarantee unless measured |

**Non-substitution (mandatory):**

```text
  container "healthy"     ≠  every tool capability available
  K8s Ready               ≠  policy allow or domain backend up
  compose stack up        ≠  authenticated multi-tenant production
  example manifests apply ≠  hardened site configuration
  /health 200             ≠  /health/ready 200
  persistence volume      ≠  backup / DR proven
```

---

## 1. Purpose and audience

| Audience | Use this guide to |
| --- | --- |
| **Operator / SRE** | Pick a mode (local → service → container → K8s example), configure env, mount data, probe health |
| **Developer** | Run a local HTTP or stdio server that matches package entrypoints |
| **Agent** | Follow labeled modes without inventing a second deployment architecture |

---

## 2. Deployment mode map

```text
  [Local process]  ── Supported ──  python -m ipfs_datasets_py.mcp_server
        │                            (stdio default | --http)
        v
  [Host service]   ── Example ────  systemd / supervisor / CLI wrappers
        │                            (MCP_SYSTEMD_SETUP.md)
        v
  [Container]      ── Supported* ─  Docker images + docker-compose.mcp.yml
        │                            (*compose is example topology)
        v
  [Kubernetes]     ── Example ────  deployments/kubernetes/*
        │
        v
  [Partial / optional sidecars]
        ├── IPFS Kubo node (compose profile)     Optional
        ├── MCP dashboard                          Optional / product surface
        ├── P2P TaskQueue / cache                  Optional
        └── Neo4j, provers, LLM, vector backends   Optional external services
```

| Mode | How you start | Support label | Primary use |
| --- | --- | --- | --- |
| **Local stdio** | `python -m ipfs_datasets_py.mcp_server` or `--stdio` | **Supported** | VS Code / MCP clients; default CLI path |
| **Local HTTP** | `python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002` | **Supported** | Health/metrics probes; HTTP tool carriers |
| **CLI lifecycle** | `ipfs-datasets mcp start|stop|status` (when packaging exposes CLI) | **Supported** (install-path dependent) | Host convenience over module entry |
| **Systemd unit** | Host unit files under site control | **Example** | Long-lived HTTP on a VM |
| **Docker (MCP image)** | `docker build -f …Dockerfile…` + `docker run` | **Supported** images; **example** run flags | Isolated process + reproducible deps |
| **Docker Compose MCP stack** | `docker-compose -f docker/docker-compose.mcp.yml up` (or root `docker-compose.mcp.yml` copy) | **Example** multi-service topology | Server + dashboard + optional IPFS |
| **Kubernetes** | `deployments/kubernetes/mcp-deployment.yaml` et al. | **Example** | Multi-replica HTTP; site must replace secrets/images |
| **Simple / standalone Flask** | `simple_server` / `standalone_server.py` | **Unsupported** as production-canonical peer | Migration / degraded only ([ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md)) |
| **Legacy Flask / class registries** | historical paths | **Unsupported** for new work | Historical |

**Default operator path:** local **stdio** for clients; local or container
**HTTP** when you need `/health`, `/health/ready`, and `/metrics`. Prefer the
**canonical** module entry over standalone/simple servers.

---

## 3. Prerequisites (all modes)

### 3.1 Runtime

| Requirement | Check | If missing |
| --- | --- | --- |
| Python 3 with package importable | `python -c "import ipfs_datasets_py; print('ok')"` | Editable install or fix `PYTHONPATH` |
| Canonical MCP stack for real protocol | Construct/run `python -m ipfs_datasets_py.mcp_server` | Install MCP/FastMCP deps; do not promote simple server |
| ASGI for HTTP | `hypercorn[trio]` preferred, else `uvicorn` | HTTP mode exits with install hint; use stdio |
| Writable state dirs when features need them | See §5 | Feature soft-disable or fail at first use |
| Free port (HTTP) | `ss -ltnp \| grep <port>` empty | Change `--port` / compose mapping |

### 3.2 Canonical CLI flags (`__main__.py`)

| Flag | Default | Notes |
| --- | --- | --- |
| `--stdio` | Default when `--http` absent | MCP client attachment |
| `--http` | off | Binds host/port; ASGI stack required |
| `--host` | `127.0.0.1` | **Do not** bind `0.0.0.0` without auth/TLS plan |
| `--port` | `3002` | Compose/K8s examples often use `8000` — site choice |
| `--config` | unset → in-code defaults | YAML via `load_config_from_yaml` |
| `--debug` | off | Verbose logging |

### 3.3 Selected environment variables

| Variable | Role | Label |
| --- | --- | --- |
| `IPFS_DATASETS_CONFIG` / config path via `--config` | YAML config | **Supported** |
| `IPFS_POLICY_STORE_PATH` | Policy store path | **Optional** |
| `SECRET_KEY` / `JWT_SECRET_KEY` | HTTP session/JWT material | **Required** for non-dev HTTP |
| `MCP_CORS_ORIGINS` / `MCP_ALLOWED_HOSTS` | HTTP CORS / host allowlist | **Optional** |
| `MCPPP_EXEC_TIMEOUT_S` | HTTP tool execution budget (default `30`) | **Supported** |
| `MCPPP_MAX_BODY_BYTES` | ASGI body limit (default ~10 MiB) | **Supported** |
| `MCPPP_MAX_SSE_CONNECTIONS` | SSE fan-out cap (default `50`) | **Supported** |
| `MCPPP_ALLOW_UNSIGNED_DELEGATIONS` | Relaxes UCAN path when set | **Optional** / security-sensitive |
| `MCPPP_STORAGE_DIR` | MCP++ state dir (default `~/.ipfs_datasets/state`) | **Optional** persistence |
| `IPFS_DATASETS_PROFILE_G_DB` | Profile G persistence | **Optional** |
| `IPFS_DATASETS_SECRETS_VAULT_FILE` | Secrets vault file | **Optional** |
| `IPFS_DATASETS_PY_*` import gates | Hermetic imports ([RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md) §4) | **Optional** |
| OTEL_* | Trace export | **Optional** |

Do **not** commit real secrets into ConfigMaps, compose files, or tickets.
Example Kubernetes secrets in-tree use placeholder base64 values — **replace
before any shared deployment**.

---

## 4. Mode procedures

### 4.1 Local process (Supported)

**Goal:** package-importable process under operator control.

```bash
# Stdio (canonical client path)
python -m ipfs_datasets_py.mcp_server
python -m ipfs_datasets_py.mcp_server --stdio --config config/mcp_config.yaml

# HTTP (health + metrics surface)
python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002
```

**Expected state:**

| Mode | Expected |
| --- | --- |
| Stdio | Process attached to client; hierarchical meta-tools registered |
| HTTP | Listener on host:port; `/health`, `/health/ready`, `/metrics` when FastAPI service path is active |

**Port note:** module default is **3002**; several Docker/K8s **examples** use
**8000**. Document the port you actually bind.

Full start/stop/discover/invoke: [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md).

### 4.2 Host service (Example)

Long-lived HTTP behind a process supervisor is a **site-specific example**.
See [MCP_SYSTEMD_SETUP.md](../MCP_SYSTEMD_SETUP.md) for unit sketches.

| Concern | Guidance |
| --- | --- |
| User | Non-root dedicated user |
| Restart | `Restart=on-failure` with backoff; avoid crash loops without journal review |
| Stop grace | `TimeoutStopSec` ≥ in-flight tool timeout (often 30–60s) |
| Logs | journald or file with rotation; scrub secrets |
| Bind | Prefer loopback + reverse proxy TLS rather than raw public bind |

**Unsupported as universal claim:** “systemd is the only production path.”

### 4.3 Container (Supported images, Example topology)

#### Images (tree)

| Artifact | Role | Label |
| --- | --- | --- |
| `docker/Dockerfile.mcp-minimal` | Slim MCP server image used by compose | **Supported** build path |
| `ipfs_datasets_py/mcp_server/Dockerfile` | MCP server image with HEALTHCHECK | **Supported** build path |
| `Dockerfile.dashboard-minimal` / `Dockerfile.dashboard` | Dashboard surface | **Optional** product UI |
| `Dockerfile.simple` / `Dockerfile.mcp-simple` / standalone variants | Reduced surfaces | **Example** / degraded — not equal to canonical |
| GPU / test Dockerfiles | CI and specialized builds | **Optional** / CI |

#### Compose stack (`docker/docker-compose.mcp.yml`) — Example topology

| Service | Port mapping (example) | Healthcheck | Notes |
| --- | --- | --- | --- |
| `mcp-server` | `8000:8000` | `curl -f http://localhost:8000/health` | Command: dependency check + `python -m ipfs_datasets_py.mcp_server --host 0.0.0.0 --port 8000` |
| `mcp-dashboard` | `8899:8899` | `curl -f http://localhost:8899/api/mcp/status` | Depends on server healthy |
| `ipfs` | `4001`, `5001`, `8082→8080` | (image default) | **Optional** Kubo node |
| `browser-tests` | — | — | Profile `testing` only |

```bash
# Example: from repo context that matches compose build context
docker compose -f docker/docker-compose.mcp.yml up -d mcp-server
docker compose -f docker/docker-compose.mcp.yml ps
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8000/health/ready
```

Volumes in compose (`mcp_data`, `dashboard_data`, `ipfs_data`) are **local
named volumes** — not a backup strategy. Mount host paths when you need
operator-owned retention.

**Hardening checklist before shared use (not automatic in compose):**

1. Replace demo secrets / JWT material
2. Restrict published ports (localhost or private network)
3. Pin image digests; drop `:latest` habits for shared clusters
4. Decide which optional tools/extras the image must include
5. Resource limits (`mem_limit`, cgroup) — see [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md)

### 4.4 Kubernetes (Example)

Tree: `deployments/kubernetes/`

| File | Role | Label |
| --- | --- | --- |
| `mcp-deployment.yaml` | Namespace, ConfigMap, Secret placeholders, Deployment, probes, resource requests/limits | **Example** |
| `mcp-ingress.yaml` / `ingress.yaml` | Ingress sketches | **Example** |
| `monitoring.yaml` | Prometheus scrape config + alert rules | **Example** |
| `infrastructure.yaml` | Supporting infra sketches | **Example** |
| `graphrag-deployment.yaml` | GraphRAG-oriented deployment sketch | **Example** / domain-specific |
| `deploy.sh` / `test.sh` | Helper scripts | **Example** |

**Illustrative resource envelope** (from `mcp-deployment.yaml` — **example**,
not a measured capacity proof):

| Setting | Example value |
| --- | --- |
| Replicas | `3` |
| RollingUpdate | `maxSurge: 1`, `maxUnavailable: 0` |
| requests | cpu `250m`, memory `512Mi` |
| limits | cpu `500m`, memory `1Gi` |
| liveness | `GET /health` port 8000 |
| readiness | `GET /health` port 8000 (site should prefer `/health/ready` when the image serves it) |
| startupProbe | `/health` with failureThreshold 6 |
| scrape annotations | `prometheus.io/path: /metrics` |

**Important drift to label:**

- Manifest command example uses `standalone_server.py --server-only` — that is
  an **example / compatibility** entry. Prefer image CMD that runs
  `python -m ipfs_datasets_py.mcp_server --http …` for **canonical** ops.
- Readiness probe path in the example hits `/health` (liveness-equivalent).
  When the FastAPI service is present, prefer **`/health/ready`** for readiness
  so load balancers drain not-ready pods ([§6](#6-health-and-readiness)).
- Secrets in the sample are **placeholders** — unsupported for production as-is.

```bash
# Example apply (cluster and image registry are site-specific)
kubectl apply -f deployments/kubernetes/mcp-deployment.yaml
kubectl -n ipfs-datasets-mcp get pods
kubectl -n ipfs-datasets-mcp port-forward svc/mcp-server-service 8000:8000  # if Service defined in your apply set
```

**Unsupported:** treating sample Secrets (`admin123` style placeholders) as
secure defaults.

---

## 5. Persistence and external services

### 5.1 What may be persisted

| Data | Typical location | Mode | Failure if missing |
| --- | --- | --- | --- |
| MCP++ / Profile state | `MCPPP_STORAGE_DIR` (~`/.ipfs_datasets/state`) | **Optional** | In-memory / feature unavailable |
| P2P TaskQueue DuckDB | `Configs.p2p_queue_path` (~`/.cache/ipfs_datasets_py/task_queue.duckdb`) | **Optional** | P2P queue disabled/degraded |
| Policy store | `IPFS_POLICY_STORE_PATH` | **Optional** | Policy stages soft-skip or unset |
| Secrets vault file | `IPFS_DATASETS_SECRETS_VAULT_FILE` | **Optional** | Empty vault |
| Profile G DB | `IPFS_DATASETS_PROFILE_G_DB` | **Optional** | Profile G features unavailable |
| HuggingFace / embedding caches | user cache dirs | **Optional** | First-call cold download |
| IPFS repo (Kubo) | compose `ipfs_data` volume | **Optional** external | IPFS tools error or offline path |
| Event DAG / audit artifacts | process-configured stores | **Optional** | Observability gap, not auto-allow |

Identity and content addressing are **not** redefined by cache presence —
[STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md).

### 5.2 External services (operator checklist)

| Service | Why connected | Required for core MCP? | Degraded behavior |
| --- | --- | --- | --- |
| **IPFS** (Kubo / kit) | pin/get/block paths | No | Tools return structured unavailable/errors ([ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) feature degrade) |
| **Vector stores / embeddings models** | search & embedding tools | No | Per-tool import or runtime errors |
| **Graph / Neo4j** | graph tools | No | Category tools fail or skip |
| **LLM / prover binaries** | generation & proof | No | Fail closed on trust claims; feature off for compute |
| **Object storage / HTTP APIs** | scrapers, datasets | No | Timeouts / unavailable |
| **Prometheus / OTel collector** | scrape and export | No | Metrics local-only or no-op spans |
| **Dashboard** | human UI | No | API-only operation remains valid |

Core inequality: **missing optional backend ≠ authorization allow**.

### 5.3 Config file example

Repository sample: `config/mcp_config.yaml` (server log level, enabled tool
categories, embedding tool schemas). Treat as **example** structure; validate
against current `Configs` fields when overriding.

---

## 6. Health and readiness

Authority for MCP HTTP probes: `fastapi_service.py` and
[AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md).

| Endpoint | HTTP meaning | Operator meaning |
| --- | --- | --- |
| `GET /health` | **200** while process handles requests | **Liveness** — process up |
| `GET /health/ready` | **200** all checks ok; **503** otherwise | **Readiness** — metrics collector + tool manager categories |
| `GET /metrics` | Prometheus text | Observability scrape |
| `GET /admin/health` | Auth-gated detailed health | Admin inspection |
| Dashboard `/api/mcp/status` | Dashboard-specific | UI dependency probe (compose) |

**Readiness checks (current FastAPI path):**

1. Metrics collector constructible
2. Hierarchical tool manager can discover categories (warns if zero categories)

```bash
# Supported local/container probes (adjust host/port)
curl -sfS --max-time 5 http://127.0.0.1:3002/health
curl -sfS --max-time 5 http://127.0.0.1:3002/health/ready
curl -sS  --max-time 5 http://127.0.0.1:3002/metrics | head
```

| Probe result | Traffic action |
| --- | --- |
| `/health` fail | Restart / replace instance (liveness) |
| `/health` ok, `/health/ready` 503 | Keep process for debug; **remove from LB** until ready |
| both ok | Eligible for traffic **≠** every tool works |
| stdio-only deploy | No HTTP probes — use process presence + discover meta-tools |

Stdio deployments: see runbook capability probe section without inventing fake
HTTP health.

---

## 7. Networking, bind addresses, and security surface

| Setting | Local Supported default | Container/K8s Example | Guidance |
| --- | --- | --- | --- |
| Bind host | `127.0.0.1` | `0.0.0.0` inside network namespace | Public exposure requires auth, TLS, allowlists |
| Ports | `3002` module default | `8000` compose/K8s examples | Document actual mapping |
| CORS / allowed hosts | localhost-favoring defaults | site override | Tighten for shared hosts |
| Body size | `MCPPP_MAX_BODY_BYTES` ~10 MiB | same | Raise only with capacity plan |
| Rate limits (selected HTTP routes) | in-process windows (e.g. embeddings 100/h, search 1000/h, admin 50/h) | same process model | Not a cluster-wide limiter unless externalized |

Auth demo paths that accept weak credentials are **unsupported** as production
identity. Wire real IdP/JWT validation before multi-tenant exposure.

---

## 8. Resource and concurrency knobs (deployment view)

Detailed capacity planning: [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md).

| Knob | Typical source | Label |
| --- | --- | --- |
| Container/K8s CPU & memory requests/limits | compose / `mcp-deployment.yaml` examples | **Example** envelopes |
| Tool timeouts | `Configs.tool_timeout` (60s), `MCPPP_EXEC_TIMEOUT_S` (30s) | **Supported** defaults |
| Workers field in K8s ConfigMap sample | `workers: 4` | **Example** — verify process model actually uses it |
| SSE connection cap | `MCPPP_MAX_SSE_CONNECTIONS` | **Supported** |
| P2P enable + startup wait | `p2p_enabled`, `p2p_startup_timeout_s` ~2s | **Optional** |
| Rate limit tables | `fastapi_service` endpoint windows | **Supported** in-process |

Do not copy example `512Mi`/`1Gi` limits as universal truth for embedding or
GraphRAG workloads — measure ([PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md)).

---

## 9. Deployment verification checklist

After any new environment:

1. **Import** — `python -c "import ipfs_datasets_py"`
2. **Start** — canonical module entry (stdio or HTTP)
3. **Liveness** — `/health` 200 (HTTP) or process alive (stdio)
4. **Readiness** — `/health/ready` 200 when using HTTP FastAPI path
5. **Discover** — categories/tools list non-empty (runbook §6)
6. **Safe invoke** — one known-safe tool or meta-tool (runbook §8)
7. **Metrics** — `/metrics` scrapeable if observability required
8. **Persistence** — confirm volumes/paths exist **before** relying on state
9. **Optional deps** — document which backends are intentionally absent
10. **Rollback path** — previous image tag / git SHA known ([DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md))

---

## 10. Migration and rollback (deployment-scoped)

| Change | Safe approach | Rollback |
| --- | --- | --- |
| Image upgrade | Rolling update with readiness gate; keep prior tag | Redeploy previous digest |
| Config change | Apply ConfigMap/env; rolling restart | Restore prior config revision |
| Compose upgrade | `pull`/`build` then `up`; keep volume names | `up` previous compose + image tags |
| Entry path simple → canonical | Stop simple; start module entry; re-discover | Document why simple was required (deps) |
| Enable optional P2P/IPFS | Feature flag + health; accept core-without-P2P | Disable flag; restart |
| Secret rotation | Dual-valid window if possible; restart pods | Prior secret revision from vault (not git) |

**Never** roll forward by disabling all policy gates “just to go green” without
change control. Trust fail-closed: [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md).

---

## 11. Unsupported and deferred paths (explicit)

| Path | Why unsupported / deferred |
| --- | --- |
| `simple_server` / incomplete Flask peers as “the” architecture | [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |
| Sample K8s secrets committed in-tree | Placeholders only |
| Assuming `/health` readiness equivalence | Ready checks differ when `/health/ready` exists |
| Multi-region active-active DR | Not a documented product guarantee in this guide |
| Managed cloud marketplace installers | Out of tree unless separately provisioned |
| GPU runners / CI self-hosted fleets | Covered under deployment/runner guides — optional CI, not core runtime contract |

---

## 12. Related documents

| Doc | Role |
| --- | --- |
| [MCP_SERVER_RUNBOOK.md](MCP_SERVER_RUNBOOK.md) | Start → discover → probe → invoke → stop |
| [PERFORMANCE_AND_CAPACITY.md](PERFORMANCE_AND_CAPACITY.md) | Limits, caches, benchmarks, targets |
| [DIAGNOSTICS_AND_RECOVERY.md](DIAGNOSTICS_AND_RECOVERY.md) | Failures, inspection, restart/migration/rollback |
| [RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md) | All product entry surfaces |
| [DEPENDENCY_AND_INITIALIZATION.md](../../architecture/DEPENDENCY_AND_INITIALIZATION.md) | Lazy/optional init |
| [DOCKER_DEPLOYMENT_GUIDE.md](../../deployment/DOCKER_DEPLOYMENT_GUIDE.md) | Longer Docker walkthrough (verify against current compose paths) |

---

## 13. Change log

| Date | Note |
| --- | --- |
| 2026-08-03 | Initial `DeploymentRuntimeGuide@1` for IPFSDOC-062 / IPFSDOC-G101 |
