# P2P workflows, distribution, and publication

| Field | Value |
| --- | --- |
| Interface | `P2PDistributionArchitecture@1` |
| Task | `IPFSDOC-024` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/p2p_networking/`; `ipfs_datasets_py/ipfs_cluster/cluster_engine.py`; `ipfs_datasets_py/huggingface/`; `ipfs_datasets_py/caching/task_p2p_cache.py`; `ipfs_datasets_py/mcp_server/tools/p2p_tools/`; `ipfs_datasets_py/mcp_server/tools/p2p_workflow_tools/`; CLI `p2p` group in `ipfs_datasets_cli.py`; packaging extras (`libp2p`); bootstrap multiaddrs in config templates |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after peer, scheduler, cluster, or publication boundary changes |

> **Companion:** Content identity (CID/IPLD/CAR) lives in
> [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md). Backend
> routers, pins, and general caches live in
> [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md). This guide
> owns **how work and content move across peers and publication surfaces**—not
> how a single process names or stores bytes locally.

## 1. Purpose

This guide answers: **how peer discovery, task/workflow scheduling, transport
handoffs, IPFS cluster retention, and Hugging Face publication fit together;
what network and identity assumptions hold; and how timeout, cancel, retry, and
offline/degraded paths behave.** It separates real distributed completion from
stubs, mocks, and simulated peer results so agents and operators do not treat
demo payloads as production evidence.

## 2. Audience

- **Primary:** developers and operators wiring multi-runner, multi-node, or
  Hub-published dataset distribution.
- **Secondary:** architects drawing trust boundaries; agents interpreting P2P
  MCP/CLI results without inventing completion or identity.

## 3. Scope and non-goals

### In scope

- Peer discovery, registry, connectivity, and bootstrap assumptions.
- Task queue and workflow scheduling (local P2P scheduler vs MCP++ engines).
- Transport and storage handoffs: libp2p-facing surfaces, backend router,
  pin/cluster, encrypted task-P2P cache.
- IPFS cluster roles vs single-node pin vs content identity.
- Hugging Face publication: dry-run receipts, append-only commit, verification.
- Network and identity assumptions (peer id vs CID vs commit SHA vs receipt).
- Timeout, cancel, retry, and offline/degraded states.
- Explicit labeling of stub, mock, and simulated paths.

### Non-goals

- Canonical byte profiles and CID math (content-addressing guide).
- General backend provider priority and process-local cache managers
  (storage/backends guide).
- Full production IPFS Cluster operator product or libp2p daemon packaging.
- Immutable dataset build/load product lifecycle detail (planned sibling
  `IMMUTABLE_DATASET_RELEASES` / IPFSDOC-025 when present).
- Authorization, UCAN, or solver proof kernels—they may *consume* digests and
  publication receipts; they are not distribution completion.
- Implementing production code changes in this documentation task.

## 4. Context

IPFS Datasets Python must move **content** and **work** beyond a single
process:

1. **Content** is identified by canonical bytes → CID (ADR-001). Location
   (which peer, pin set, Hub path, gateway) is not identity.
2. **Work** is scheduled as workflows/tasks across peers so non-critical
   pipelines (code gen, scrape, data processing) can bypass GitHub API when
   tagged for P2P.
3. **Publication** promotes verified local releases to external surfaces
   (IPFS pin/cluster retention; Hugging Face append-only releases) with
   labeled receipts.
4. **Optional stacks** (py-libp2p, `ipfs_accelerate_py` / MCP++, GitHub CLI,
   Hub tokens) are often absent. Feature degradation is allowed; inventing
   distributed success is not (ADR-002, ADR-004).

Collapsing these layers produces false confidence: a stub
`DistributedDatasetManager` “success”, a mock cluster pin, or synthetic
`QmPeer…` discovery results are **not** distributed completion.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Peer registry / connectivity configuration contracts | Content CID profiles and IPLD codecs |
| Workflow tags, local merkle-clock assignment, fibonacci priority queue | GitHub Actions product runtime or GHA billing |
| Task queue / workflow engine *API shape* and degraded responses | Guaranteed live multi-peer mesh without optional deps |
| Cluster *helper* / mock service semantics | Full IPFS Cluster consensus operator product |
| Hugging Face publication plan/receipt/verify boundary | Hosting of Hub or IPFS infrastructure |
| Labeling stub vs live transport | General `CacheManager` / API HTTP caches |

**Inbound callers:** CLI (`ipfs-datasets p2p …`), MCP `p2p_tools` /
`p2p_workflow_tools` / cluster tools, Python API over
`ipfs_datasets_py.p2p_networking`, caching adapters, release/publish scripts.

**Outbound dependencies:** optional py-libp2p (extra); MCP++ /
`ipfs_accelerate_py` for peer registry and task queue wrappers; GitHub CLI
(`gh cache`) for Actions peer registry; Kubo/IPFS backends via router for
content put/get/pin; Hugging Face Hub API (injected `HfApi`) for publish;
bootstrap multiaddrs (`bootstrap.libp2p.io` defaults).

**Authority notes:** A peer connection id, pin status, HF commit SHA, dry-run
cost receipt, and content CID answer different questions. Do not rename one
into another in logs or agent prompts (ADR-001 kinds of truth).

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package entry | `p2p_networking/__init__.py` | Lazy submodule import; optional `PeerEngine` / `TaskQueueEngine` / `WorkflowEngine` |
| Peer registry (GHA) | `p2p_networking/p2p_peer_registry.py` | `P2PPeerRegistry`: register/discover via GitHub Actions cache + `gh` |
| Connectivity | `p2p_networking/p2p_connectivity.py` | `ConnectivityConfig`, `UniversalConnectivity` (TCP/QUIC/WebRTC flags, mDNS, DHT, relay, AutoNAT, hole punch) |
| Workflow scheduler | `p2p_networking/p2p_workflow_scheduler.py` | `MerkleClock`, `FibonacciHeap`, `WorkflowDefinition`, `P2PWorkflowScheduler`, hamming assignment |
| Peer engine | `p2p_networking/peer_engine.py` | Discover/connect/disconnect/list/metrics/bootstrap; degrades without MCP++ |
| Task queue engine | `p2p_networking/taskqueue_engine.py` | Submit/status/cancel/list/retry/workers; requires MCP++ wrapper |
| Workflow engine | `p2p_networking/workflow_engine.py` | Submit/status/cancel/list/deps/result via MCP++ scheduler |
| libp2p surfaces | `libp2p_kit.py`, `libp2p_kit_stub.py`, `libp2p_kit_full.py` | Import-safe stub; full module is MCP++ compatibility facade (no raw host create in current path) |
| P2P CLI helpers | `p2p_networking/cli.py` | Connectivity-oriented CLI with timeout flags |
| Cluster engine | `ipfs_cluster/cluster_engine.py` | `MockIPFSClusterService` for tool demos |
| Task P2P cache | `caching/task_p2p_cache.py` | Encrypted MCP++ TaskQueue cache client; no raw libp2p host |
| HF publication | `huggingface/publisher.py` (+ `release.py`, repository/snapshot) | Dry-run cost receipt, append-only publish, post-publication verify |
| MCP tools | `mcp_server/tools/p2p_tools/`, `p2p_workflow_tools/`, cluster tools | Thin wrappers over engines/schedulers |
| CLI group | `ipfs_datasets_cli.py` (`p2p` subcommands) | init / schedule / next / status / peers / tags |

```text
  CLI / MCP / Python API
           |
           +------------------+-------------------+------------------+
           |                  |                   |                  |
           v                  v                   v                  v
   P2PWorkflowScheduler   PeerEngine        TaskQueueEngine   HF publisher
   (local assignment)     WorkflowEngine    (MCP++ wrapper)   (Hub boundary)
           |                  |                   |                  |
           |                  v                   v                  |
           |           discovery/registry    task cancel/retry       |
           |           connect/bootstrap     worker register         |
           |                  |                   |                  |
           +--------+---------+---------+---------+                  |
                    |                   |                            |
                    v                   v                            v
            Connectivity / libp2p   Backend router / pins      Commit SHA +
            multiaddr assumptions   IPFS cluster mock/live     verify receipt
                    |                   |
                    v                   v
              peer_id / multiaddr    CID (identity)  ≠  pin status (retention)
```

## 7. Peer discovery, registry, and connectivity

### 7.1 Discovery channels

| Channel | Mechanism | When it applies | Notes |
| --- | --- | --- | --- |
| GitHub Actions cache registry | `P2PPeerRegistry` + `gh cache upload/list` | Self-hosted runners sharing a repo | Peer TTL default 30 minutes; public IP probe for NAT context |
| mDNS | `UniversalConnectivity` flags | Same LAN | Interval/TTL configurable; loop is **caller-managed** (no background spawn in module) |
| DHT | Configured on host path | Wide-area routing | Query timeout default 60s; real DHT requires live libp2p stack |
| Bootstrap multiaddrs | Config templates + `PeerEngine.bootstrap` | Cold start | Defaults include `/dnsaddr/bootstrap.libp2p.io/p2p/Qm…` nodes |
| Explicit peers | Scheduler `peers=` list; connect multiaddr | Controlled meshes | Deterministic assignment needs known peer set |

`UniversalConnectivity.discover_peers_multimethod` unions GitHub registry,
mDNS (placeholder when stack unavailable), DHT (placeholder), and bootstrap
addresses. Empty discovery is a valid offline/degraded outcome—not a failure
to invent peers.

### 7.2 Registry record shape (GHA)

Registration stores approximately:

- `peer_id` — libp2p peer identity string
- `runner_name` — `RUNNER_NAME` or hostname
- `public_ip`, `listen_port`, `multiaddr`
- `last_seen` (UTC ISO)
- optional `metadata`

Discovery filters by cache key prefix, skips self, and applies TTL.
`heartbeat` re-registers; `cleanup_stale_peers` removes expired entries when
`gh` allows. Subprocess timeouts for `gh` are typically **30s**; IP probe
services use **5s**.

### 7.3 Connectivity stack

`ConnectivityConfig` toggles:

| Flag | Default | Role |
| --- | --- | --- |
| `enable_tcp` | true | Primary transport |
| `enable_quic` | false | Experimental |
| `enable_webrtc` | false | Browser path (optional) |
| `enable_mdns` | true | Local discovery |
| `enable_dht` | true | Distributed routing |
| `enable_relay` | true | Circuit relay (hop limit 3, timeout 30s) |
| `enable_autonat` | true | Reachability classification |
| `enable_hole_punching` | true | Prefer direct path after NAT |

Connection attempt order (when implemented on a live host): **direct → relay
fallback**. Reachability may be recorded as `public` / `private` / `unknown`.
A path that only *simulates* AutoNAT and sets `"unknown"` must not be reported
as verified public reachability.

### 7.4 PeerEngine lifecycle

| Operation | Behavior | Degraded without MCP++ |
| --- | --- | --- |
| `discover` | Capability filter, max_peers, timeout (default 30s) | `success: false`, `degraded_mode: true`, empty `peers` |
| `connect` | Retries (default 3), timeout 30s, optional persist | unavailable payload with peer_id/multiaddr |
| `disconnect` | Graceful or force | unavailable |
| `list_peers` / `get_metrics` | Registry-backed when available | empty / unavailable |
| `bootstrap` | Default libp2p bootstrap multiaddrs | unavailable |

**Critical honesty rule:** Some success-shaped discover/connect code paths
build **synthetic** peer ids (`QmPeer{i}…`) and multiaddrs for tooling demos.
Those results are **not** distributed completion and must not be stored as
proof of mesh membership. Treat as incomplete unless the operator has a live
registry and independent connectivity evidence.

## 8. Task and workflow scheduling

Two layers coexist; do not merge their semantics.

### 8.1 Local P2P workflow scheduler

`P2PWorkflowScheduler` (`p2p_workflow_scheduler.py`) is **in-process**:

1. **Tags** decide eligibility (`WorkflowTag`):
   - `github_api` / `unit_test` → must use GitHub API (not P2P-assigned here)
   - `p2p_eligible` / `p2p_only` → may/must run via P2P
   - domain tags: `code_gen`, `web_scrape`, `data_processing`
2. **Merkle clock** ticks on schedule; hash forms causal content-addressable
   clock state; `merge` combines concurrent peer clocks.
3. **Responsible peer** = minimum **hamming distance** between
   `hash(clock_head ‖ task_hash)` and `hash(peer_id)` over the known peer set.
4. **Fibonacci heap** prioritizes local queue (lower priority value first).
5. Returns `assigned_peer`, `is_local`, `clock_hash`, queue size when local.

CLI: `ipfs-datasets p2p init|schedule|next|status|add-peer|remove-peer|tags|assigned`.
MCP: `initialize_p2p_scheduler`, `schedule_p2p_workflow`, `get_next_p2p_workflow`,
`get_p2p_scheduler_status`.

**What “scheduled” means here:** deterministic *assignment intent* among the
configured peer id set. It does **not** by itself prove remote execution,
artifact pin, or publication.

### 8.2 MCP++ TaskQueueEngine and WorkflowEngine

When `ipfs_accelerate_py` / MCP++ is present:

| Engine | Core ops | Fail closed shape |
| --- | --- | --- |
| `TaskQueueEngine` | submit (timeout, retry_policy), get_status, cancel, list, set_priority, get_result, stats, pause/resume/clear, retry, register/unregister worker, worker status | `status: unavailable`, install message for accelerate |
| `WorkflowEngine` | submit, get_status, cancel, list, dependencies, get_result | explicit “MCP++ not available — cannot …” errors |

Cancel supports `reason` and `force`. Retry accepts `retry_config` and returns
`retry_task_id` / `retry_count` when the wrapper succeeds. Worker unregister
uses a graceful timeout (default **300s**).

Without the wrapper, engines return structured **unavailable**—not fake
completed tasks.

## 9. Transport and storage handoffs

Distribution is a **pipeline of handoffs**, each with its own success criteria:

```text
1. Schedule / assign work     → assigned_peer, task_id, clock_hash
2. Transport intent           → multiaddr connect, protocol id, timeout
3. Materialize bytes          → local path, CAR, or block put
4. Content address            → CID (identity)  [content-addressing guide]
5. Store / retrieve           → backend router cat/add/block_*  [storage guide]
6. Retain                     → pin or cluster pin_content (availability)
7. Optional share cache       → TaskP2PCacheAdapter (encrypted, namespaced)
8. Optional publish           → HF append-only commit + verify receipt
```

### 9.1 libp2p-facing transport

| Surface | Reality in tree |
| --- | --- |
| `libp2p_kit.py` / `libp2p_kit_stub.py` | Minimal **stub** for import safety; methods return stub/mock success shapes |
| `libp2p_kit_full.py` | Historical distributed dataset models (`NodeRole`, shard metadata, protocol ids); runtime network ops are intended to route through MCP++ transport—not re-create raw hosts/plaintext streams |
| Packaging | `libp2p` optional extra (often git install of py-libp2p) |
| Protocols (documented models) | e.g. `/ipfs_datasets/shard/1.0.0`, `transfer`, `sync`, federated search |

**Rule:** Importing `DistributedDatasetManager` and receiving
`{"status": "success", "message": "Stub implementation"}` is **not**
distributed completion.

### 9.2 Content path handoff

Work that produces dataset/IR bytes must:

1. Canonicalize and compute CID (ADR-001).
2. Persist via `ipfs_backend_router` / IPLD storage (location).
3. Optionally pin for retention.
4. Reference the CID (and optional pin receipt metadata) in task results.

Indexes and peer gossip are not identity roots. Remote raw P2P cache streams
that lack authentication are intentionally disabled or constrained (see
storage guide; Task P2P cache requires shared secret + cryptography).

### 9.3 Task P2P cache handoff

`TaskP2PCacheAdapter`:

- Uses MCP++ TaskQueue **cache RPCs** only (no raw libp2p host).
- Requires cryptography + shared secret
  (`IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` / aliases).
- Disable via `IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P` (and aliases).
- Default timeout **10s**; namespace-wrapped keys.
- Disabled reasons: `disabled`, `missing_cryptography`,
  `missing_shared_secret`, encryption init failure.

Cache hit is a **performance** outcome. It is not a publication receipt and
not content identity.

## 10. IPFS cluster and publication roles

### 10.1 Role split

| Role | Meaning | Typical module |
| --- | --- | --- |
| **Identity** | What the bytes are | CID helpers / IPLD |
| **Single-node pin** | Retain on one backend | `IPFSPinner`, router `pin` |
| **Cluster pin** | Replicate retention intent across cluster peers | cluster service / tools |
| **P2P work peer** | Execute or coordinate tasks | scheduler / engines |
| **Publication surface** | External immutable release (Hub path, commit) | `HuggingFaceReleasePublisher` |

Cluster pin success describes **availability policy outcome**, not correctness
of semantic claims and not HF publication.

### 10.2 MockIPFSClusterService

`MockIPFSClusterService` provides in-memory nodes, pins, raft-like config
fields, and `get_cluster_status` (`healthy` if any node online else
`degraded`). Methods: add/remove node, `pin_content` (replication_factor),
unpin, list pins, sync.

This mock exists for **development and MCP tool demos**. It is **not** a live
IPFS Cluster control plane. Do not treat mock pin maps as production
replication evidence.

### 10.3 Hugging Face publication

`HuggingFaceReleasePublisher` owns the remote-write boundary for release
promotion:

1. **Dry-run diff and cost receipt** — deterministic ops list, byte totals,
   estimated cost, immutable release prefix, hashes; **no write-endpoint
   contact**. Schema markers include
   `abby-voice-hf-publication-plan/v1` and cost receipt fields.
2. **Append-only commit** — injected `HfApi.create_commit` under a **new**
   release id; never basename skip, never delete/rewrite legacy objects.
   Prohibited ops include delete/move/force_push/rewrite_main.
3. **Post-publication verification** — returned commit SHA and uploaded
   digests.
4. **Pinned redownload validation** — empty verified cache by commit SHA.
5. **Canary / rollback** of runtime release pointer as a separate reviewed
   step (does not delete a failed release).

Autonomous workers stop after dry-run unless approval gates allow commit.
Tokens must never appear in task rows, manifests, logs, receipts, or source
control (`_reject_secrets`).

**Kinds of truth for publication:**

| Artifact | Kind | Not to confuse with |
| --- | --- | --- |
| Dry-run plan + cost receipt | Planning / cost **receipt** | Live Hub state |
| Commit SHA | Hub revision location | Content CID |
| File sha256 digests | Content integrity for Hub objects | libp2p peer id |
| Runtime release pointer | Mutable name for “current” | Immutable release prefix |
| Content CID of packaged bytes | Portable content identity | HF repo path |

Read path: repository revision resolution, snapshot fetch into integrity cache
(`huggingface/repository.py`, `snapshot.py`). Local builders (e.g. voice HF
release construction) write filesystem artifacts only; publication remains a
separate boundary.

## 11. Network and identity assumptions

1. **Peer id ≠ CID.** Peer ids identify network actors; CIDs identify content.
2. **Multiaddr ≠ integrity.** Reachability of `/ip4/…/tcp/…/p2p/…` does not
   validate payload bytes.
3. **Bootstrap nodes are public infrastructure defaults**, not product
   secrets and not automatic membership in a private trust domain.
4. **Known peer set for hamming assignment is operator-configured** (or
   discovered). Assignment with only `self` always assigns local—still not
   multi-peer proof.
5. **GHA cache registry depends on `gh` auth and repo permissions.** Offline
   or unauthenticated environments get empty discovery.
6. **MCP++ availability is optional.** Missing accelerate → feature off with
   structured errors (ADR-002).
7. **Simulated or stub success is never portable production identity**
   (aligned with storage guide offline CID labeling).
8. **Publication tokens are ambient secrets** (env/operator injection), never
   part of content identity or receipt payloads.
9. **Timeouts are soft availability bounds**, not proof of peer honesty.
10. **Fail-closed on trust; degrade on features** (ADR-004): missing network
    degrades distribution features; it must not mint false completion or false
    identity.

## 12. Timeout, cancel, and retry behavior

| Subsystem | Timeout / cancel / retry | Notes |
| --- | --- | --- |
| Peer registry `gh` ops | 30s subprocess timeout | Fail → log warning, empty peers / false register |
| Public IP probe | 5s per service | Multi-service fallback |
| Connectivity relay | `relay_timeout` 30s | Hop limit 3 |
| DHT query | `dht_query_timeout` 60s | Config only until live DHT |
| PeerEngine discover/connect | default timeout 30s; connect `retry_count` 3 with 1s sleep | Exhausted retries → error payload |
| Task submit | optional per-task `timeout`, `retry_policy` | Engine passes through to wrapper |
| Task cancel | `reason`, `force` | Returns `cancelled_at`, `cleanup_required` |
| Task retry | `retry_config` | New `retry_task_id` when available |
| Worker unregister | default timeout 300s, `graceful` | |
| Workflow cancel | `reason`, `force` | Reports `cancelled_steps` when wrapper works |
| Task P2P cache | default `timeout_s` 10.0 | |
| P2P networking CLI | `--timeout-s` (often 10–30s defaults) | |
| HF publish | fail-closed on plan/verify errors | No silent partial “published” without verification path |

**Cancel semantics:** cancellation is a control-plane intent on task/workflow
state. It does not unpin content or delete Hub releases unless a separate
operator procedure says so.

**Retry semantics:** retries are for **availability** (transient connect/queue
failures). They must not re-label a stub result as verified remote success.

## 13. Offline and degraded states

| Condition | Expected behavior | Must not claim |
| --- | --- | --- |
| No network / offline | Local scheduler still assigns among known peer ids; content may use local IPLD/blocks; HF dry-run may still plan if local files known | Hub commit, live cluster health, DHT mesh |
| No py-libp2p / stub kit | Imports succeed; stub methods only | Sharded P2P transfer complete |
| No MCP++ / accelerate | Engines return unavailable / degraded_mode | Task executed on remote worker |
| No `gh` / GHA cache | Registry register/discover fails soft → empty | Peer mesh formed |
| No shared secret for task P2P cache | Adapter disabled (`missing_shared_secret`) | Encrypted remote cache hit |
| Mock cluster only | Demo pin maps in process memory | Production replication factor met |
| AutoNAT simulate `unknown` | Reachability unknown | Publicly dialable |
| HF without token/approval | Dry-run only; autonomous stop | Append-only commit succeeded |
| Partial peer loss | Scheduler peer remove; reassignment policies are local logic | Automatic global failover without evidence |

**Distributed completion checklist (all required for the claim):**

1. Live transport or verified out-of-band handoff (not stub/mock alone).
2. Task/workflow status from a real queue/worker (not unavailable engine).
3. Content CID (or explicit non-CID local artifact contract) for outputs.
4. Optional pin/cluster/HF steps only if that surface was in scope—and then
   with real service receipts (commit SHA, pin response from live backend).
5. Explicit labels when any step was dry-run, mock, or degraded.

If any required step is stub/simulated, report **partial / degraded**, not
complete.

## 14. Invariants

1. **Kinds of truth stay labeled:** peer id, multiaddr, CID, pin status, task
   status, HF commit SHA, dry-run receipt.
2. **Stub or simulated peer results are never distributed completion.**
3. **Mock cluster is not production IPFS Cluster.**
4. **Local schedule assignment ≠ remote execution evidence.**
5. **Optional deps degrade features; they do not rewrite identity rules.**
6. **Publication is append-only and approval-gated; dry-run is not publish.**
7. **Secrets never enter receipts, manifests, or logs.**
8. **Caches (including task P2P cache) are not identity and not publication.**
9. **Fail closed on trust claims; fail soft on discovery emptiness.**
10. **Agents must surface `degraded_mode` / `unavailable` instead of inventing peers.**

## 15. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Separate schedule from transport | Assignment can be local and deterministic; transport is optional-heavy | `p2p_workflow_scheduler.py` vs connectivity/engines |
| GHA cache as peer rendezvous | Avoid central registry for Actions runners | `p2p_peer_registry.py` |
| MCP++ for live task mesh | Keep raw libp2p host creation out of datasets import path | `libp2p_kit_full.py` module doc; engines |
| Stub import surface | Prevent hang/import failures in CI without extras | `libp2p_kit.py` |
| Encrypted task cache only | Avoid unauthenticated P2P cache poisoning | `task_p2p_cache.py`; storage guide |
| HF dry-run + verify | Autonomous safety; append-only releases | `huggingface/publisher.py` |
| Identity vs location | Multi-peer retrieval without changing artifact ids | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Feature vs trust degrade | Empty peers OK; fake proof not OK | [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

## 16. Security, privacy, and trust boundaries

- Untrusted peers can advertise multiaddrs and serve wrong bytes; clients must
  recompute CIDs/digests for high assurance.
- GHA peer registry entries are only as trustworthy as repo cache write access.
- Shared secrets for task P2P cache define a **trust domain**; missing secret
  disables the feature rather than sending plaintext.
- Cluster and pin APIs are privileged retention operations—gate with product
  authz, not mere CID possession.
- HF tokens: inject at commit time; never persist in plans/receipts.
- Do not pin or publish secrets under public CIDs or public Hub paths.
- Synthetic discover/connect success paths are tool scaffolding—treat as
  untrusted for security decisions.

## 17. Observability and operations

- Scheduler: `get_status`, queue size, assigned workflow ids, clock hash.
- PeerEngine: discover counts, connection attempts, metrics when enabled.
- Task queue: status, progress, logs/metrics flags, worker registration.
- Cluster mock: `get_cluster_status` (online nodes, pin counts, health).
- HF: dry-run cost receipt fields; post-publication verification outcomes.
- Operator knobs: connectivity flags; env disables for task P2P cache; bootstrap
  multiaddrs in config; `HUGGINGFACE_TOKEN` / injected API for publish.
- CLI: `ipfs-datasets p2p status` for local scheduler; cluster MCP tools for
  mock service demos.

## 18. Validation

```bash
test -s docs/architecture/storage/P2P_AND_PUBLICATION.md && rg -n \
  'libp2p|peer|task|IPFS|Hugging Face|offline|receipt' \
  docs/architecture/storage/P2P_AND_PUBLICATION.md

# Implementation anchors (read-only checks)
rg -n 'class P2PPeerRegistry|class UniversalConnectivity|class P2PWorkflowScheduler' \
  ipfs_datasets_py/p2p_networking/
rg -n 'class PeerEngine|class TaskQueueEngine|class WorkflowEngine' \
  ipfs_datasets_py/p2p_networking/
rg -n 'class MockIPFSClusterService' ipfs_datasets_py/ipfs_cluster/cluster_engine.py
rg -n 'class HuggingFaceReleasePublisher|dry-run diff and cost receipt' \
  ipfs_datasets_py/huggingface/publisher.py
rg -n 'class TaskP2PCacheAdapter' ipfs_datasets_py/caching/task_p2p_cache.py
test -s ipfs_datasets_py/p2p_networking/libp2p_kit.py
```

**Limitations:** live multi-peer, live IPFS Cluster, and live Hub publish tests
require provisioned network, secrets, and optional extras. Offline validation
of this guide is documentation + static path presence only. Stub/mock modules
passing unit import tests do not constitute a distributed completion gate.

## 19. Related documentation

| Document | Relationship |
| --- | --- |
| [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | CID/IPLD/CAR identity |
| [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Routers, pins, caches |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Identifier ≠ location/receipt |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional libp2p/accelerate lifecycle |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Feature degrade vs trust fail-closed |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | kit / accelerate ownership |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Import hermeticity |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain flows |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Storage/distribution placement |
| Historical plan notes | `docs/implementation/plans/p2p_workflow_scheduler.md` (plan/usage; this guide is architecture authority for distribution map) |

## 20. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide (`IPFSDOC-024`) |
