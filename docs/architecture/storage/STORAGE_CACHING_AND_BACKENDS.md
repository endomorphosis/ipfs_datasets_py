# Storage, caching, and backends

| Field | Value |
| --- | --- |
| Interface | `StorageCacheBackendArchitecture@1` |
| Task | `IPFSDOC-023` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/ipfs_backend_router.py`; `ipfs_datasets_py/storage/storage_engine.py`; `ipfs_datasets_py/processors/storage/ipld/storage.py`; `ipfs_datasets_py/core_operations/ipfs_pinner.py`; `ipfs_datasets_py/ipfs_cluster/cluster_engine.py`; `ipfs_datasets_py/caching/`; `ipfs_datasets_py/router_deps.py`; packaging extras and env flags |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Review cadence | after router, pin, cluster, or cache manager changes |

> **Companion:** Content identity, CID profiles, IPLD codecs, and CAR
> representation live in
> [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md). This guide
> owns **where** content is stored, **how** backends are selected, **pinning**,
> and **cache trust**.

## 1. Purpose

This guide answers: **who owns storage engines versus IPFS routers, how pins
and external backends work, how caches are keyed and invalidated, and what
consistency/integrity operators can expect—including offline and recovery
paths.** It keeps **identifiers, locations, indexes, and receipts** distinct
while describing real modules in the tree.

## 2. Audience

- **Primary:** developers and operators configuring IPFS backends, pins, and
  application caches.
- **Secondary:** architects drawing trust boundaries; agents interpreting
  backend/cache errors without inventing identity.

## 3. Scope and non-goals

### In scope

- Ownership split: thin `storage` engine facade vs IPLD storage vs backend router.
- `IPFSBackend` protocol and provider resolution order.
- Pinning (`pin`/`unpin`, `IPFSPinner`, cluster mock service).
- Cache layers: IPLD block cache, router backend instance cache, `CacheManager`,
  content-validated API caches, remote/router caches.
- Cache keys, trust assumptions, TTL/stale invalidation.
- Consistency and integrity across multi-backend retrieval.
- Optional dependencies and env flags for backends/caches.
- Offline / degraded behavior and failure recovery.

### Non-goals

- Canonical byte profiles and CID math (content-addressing guide).
- P2P workflow product design and Hugging Face publication (sibling distribution
  guide when present).
- Vector ANN index algorithms and GraphRAG ranking (retrieval/knowledge leaves).
- External IPFS daemon packaging as a product deliverable of this repo.
- Implementing production code changes in this documentation task.

## 4. Context

Call sites need a stable way to **add, get, pin, and cache** content without
importing heavy optional stacks at package import time. The system therefore
separates:

1. **Identity** — CID of canonical bytes (ADR-001; content-addressing guide).
2. **Transport / location** — which backend performs `cat`/`block_get`/`pin`.
3. **Retention policy** — pin sets and cluster replication (availability).
4. **Performance cache** — process or disk memoization that must not redefine identity.
5. **Indexes** — search/vector structures that *reference* content.

Collapsing these layers produces false confidence (“it’s in cache so it’s
true”) or false identity (“the path is the id”).

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Backend selection and `IPFSBackend` operations | Canonical byte / CID profile definitions |
| Pin and unpin as **location/retention** operations | Proof that content is “correct” for a claim |
| Process-local and application cache managers | IR formal identity (`logic.ir_core`) |
| Thin storage engine models / mock storage manager | Production S3/GCS/Azure SDKs as first-class guaranteed backends |
| Cluster *helpers* and mock cluster service | Full production IPFS Cluster operator product |

**Inbound callers:** core operations (loader/saver/pinner/getter), MCP IPFS and
storage tools, IPLD storage, caching package, accelerate/kit integrations via
router.

**Outbound dependencies:** Kubo CLI (`ipfs`), optional `ipfshttpclient`,
optional `ipfs_kit_py` / `ipfs_accelerate_py`, local disk for cache dirs.

```text
                    +---------------------------+
                    |   Callers (API/MCP/CLI)   |
                    +-------------+-------------+
                                  |
          +-----------------------+------------------------+
          |                       |                        |
          v                       v                        v
  storage_engine            IPLDStorage              IPFSPinner /
  (models/mock)          (blocks + CAR)            cluster helpers
          |                       |                        |
          |                       +-----------+------------+
          |                                   |
          v                                   v
     (local mock paths)              ipfs_backend_router
                                      (IPFSBackend impls)
                                              |
                     +------------------------+------------------+
                     |            |           |                  |
                     v            v           v                  v
                  kit          HTTP API    accelerate         Kubo CLI
```

## 6. Components

### 6.1 Storage engine vs IPLD vs router

| Component | Path | Ownership |
| --- | --- | --- |
| **Storage engine facade** | `ipfs_datasets_py/storage/storage_engine.py` | Enums (`StorageType`, `CompressionType`), `StorageItem` / `Collection` dataclasses, `MockStorageManager` for tests/dev. **Not** the production IPLD block layer. |
| **IPLD storage** | `ipfs_datasets_py/processors/storage/ipld/storage.py` | Content-addressed blocks, local `_block_cache`, CAR, batch; uses router when online. |
| **Backend router** | `ipfs_datasets_py/ipfs_backend_router.py` | Stable entrypoint: `get_ipfs_backend`, `add_bytes`, `cat`, `pin`, `block_put`, `block_get`, path add/get, `dag_export`. |
| **Router deps** | `ipfs_datasets_py/router_deps.py` | Shared injectable `RouterDeps` (backend instance + caches across routers). |

**Rule of thumb:** business content-addressing → IPLD + CID helpers; multi-backend
IPFS I/O → router; generic “storage item” mocks/tools → storage engine.

### 6.2 External backends (`IPFSBackend`)

Protocol methods (all address content primarily by **CID** or raw **bytes**):

| Method | Meaning |
| --- | --- |
| `add_bytes` / `add_path` | Write content; optional pin |
| `cat` / `get_to_path` / `ls` | Read path-oriented IPFS objects |
| `block_put` / `block_get` | Raw IPLD block I/O with codec |
| `pin` / `unpin` | Retention on that backend |
| `dag_export` | DAG export bytes (when supported) |

**Resolution order** (`get_ipfs_backend` / `_resolve_backend`), after process
injection and env force:

1. Process-global override (`set_default_ipfs_backend`) or `RouterDeps.ipfs_backend`.
2. Explicit `preferred` provider or `IPFS_DATASETS_PY_IPFS_BACKEND`.
3. **ipfs_kit_py** if `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` (and not `IPFS_KIT_DISABLE`).
4. **HTTP API** if `IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI` (`ipfshttpclient` + `IPFS_HOST`).
5. **ipfs_accelerate_py** if `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE` (file-oriented; limited block API).
6. **Kubo CLI** (`IPFS_DATASETS_PY_KUBO_CMD`, default `ipfs`), with optional kit bootstrap when CLI missing.

Backend *instance* selection may be LRU-cached (`IPFS_DATASETS_PY_ROUTER_CACHE`,
default on) keyed by relevant env vars. Call
`clear_ipfs_backend_router_caches()` after env changes in-process.

**Capability gaps:** accelerate backend does not implement full `block_put` /
`block_get` / path ops—callers needing true IPLD blocks should use kit, HTTP
API, or Kubo. Kit/accelerate may return **simulated** `Qm…` identifiers when
IPFS is unavailable; those are location/availability fallbacks, not validated
CIDv1 protocol ids ([CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md)).

### 6.3 Pinning and cluster

| Component | Path | Role |
| --- | --- | --- |
| Router pin API | `ipfs_backend_router.pin` / `unpin` | Pin existing CID on selected backend |
| Core pinner | `core_operations/ipfs_pinner.py` (`IPFSPinner`) | File/directory/data pin orchestration for MCP/CLI/API |
| MCP tool | `mcp_server/tools/ipfs_tools/pin_to_ipfs.py` | Thin wrapper over domain pin logic |
| Cluster engine | `ipfs_cluster/cluster_engine.py` | `MockIPFSClusterService`: node status, pin_content with replication factor |

**Pin ≠ identity.** Pinning records a **retention/location preference** on a
backend or cluster. Unpinning does not change the CID of bytes. Cluster
replication_factor is an availability policy, not a new content id.

**Current-tree honesty:** `IPFSPinner` supports direct kit integration and MCP
client modes; some dict-input paths historically return mock CIDs for tests.
Treat production integrity paths as those that go through validated multiformats
CIDs and real backends. `MockIPFSClusterService` is explicit mock domain logic
for tools—not a live cluster control plane.

### 6.4 Cache layers

| Layer | Path / symbol | Keying | Trust |
| --- | --- | --- | --- |
| **IPLD block cache** | `IPLDStorage._block_cache` | CID → bytes | Performance only; filled from store or backend get |
| **Router backend cache** | `_resolve_backend_cached` | Env-derived tuple | Caches *which client*, not content |
| **RouterDeps cache slots** | e.g. kit instance under `ipfs_kit_py::kit_instance` | Named keys on deps | Shared process resources |
| **CacheManager** | `caching/cache_manager.py` | `namespace:key` + optional TTL | Application memoization; not content-addressed by default |
| **GitHubAPICache** | `caching/cache.py` | Operation + args key; optional multihash of **validation fields** | Content-aware stale detection when multiformats present; TTL otherwise |
| **Distributed / remote** | `caching/distributed_cache.py`, `router_remote_cache.py`, `task_p2p_cache.py` | Implementation-specific; remote P2P raw stream protocol disabled for GitHub cache | Prefer canonical services; do not treat peer gossip as integrity root |
| **Cache engine** | `caching/cache_engine.py` | Domain-specific engine helpers | Same: performance / policy, not identity |

## 7. End-to-end flow

### 7.1 Write path (bytes → backend ± pin)

```text
Caller
  -> (optional) canonical_bytes + CID   [identity layer]
  -> IPLDStorage.store / router.add_bytes / block_put
  -> backend write
  -> optional pin(cid)
  -> optional CacheManager / block_cache fill
  -> return CID  (identifier)  +  backend name  (location metadata)
```

### 7.2 Read path (CID → bytes)

```text
Caller supplies CID
  -> validate_cid when contract-critical
  -> IPLDStorage.get: block_cache hit?
       yes -> return bytes
       no  -> router.block_get / cat
  -> optional integrity: recompute CID of bytes, compare
  -> return bytes
```

### 7.3 Pin path

```text
IPFSPinner.pin(path|dict) or router.pin(cid)
  -> resolve backend (kit / HTTP / accelerate / Kubo)
  -> pin add on that backend
  -> status payload: cid, size, content_type  (availability receipt-ish metadata)
```

A successful pin response is **evidence of a pin attempt/outcome**, not a
content-identity claim and not authorization for further side effects.

### 7.4 Cache get/set path (`CacheManager`)

```text
set(namespace, key, value, ttl?)
  -> store under "namespace:key" + metadata (expires_at, access_count)
get(namespace, key)
  -> miss | expired (evict) | hit
optimize(policy)
  -> LRU / LFU / size / age eviction
```

Embeddings helpers (`cache_embeddings` / `get_cached_embeddings`) are
application convenience under the same namespace rules.

## 8. Contracts

### 8.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| CID | string | `validate_cid` for protocol fields; backend may accept broader Kubo forms for ops |
| Bytes / path | `bytes` / filesystem path | Path existence for pin/add_path; size limits at caller policy |
| Backend name | env or argument | Must be registered provider when forced |
| Cache key | string + namespace | Caller-defined; should include version/profile when caching identity-sensitive data |
| Pin flags | `pin: bool`, recursive, wrap_with_directory | Backend-specific |

### 8.2 Outputs

| Output | Type | Guarantees |
| --- | --- | --- |
| CID from store/add | string | Prefer multiformats CIDv1; may be simulated offline—label accordingly |
| Retrieved bytes | `bytes` | Equal to stored block when integrity held |
| Pin status dict | structured | Describes pin **operation**, not content truth |
| Cache get result | `{success, hit, value, reason?}` | Hit ≠ integrity attestation |
| Cluster status | mock or service payload | Availability of cluster mock/service |

### 8.3 Cache keys, trust, and invalidation

| Concern | Contract |
| --- | --- |
| **Key composition** | At minimum namespace + logical key. For content-sensitive entries, include encoding profile and content digest/CID in the key or validation fields. |
| **TTL** | `CacheManager` and `GitHubAPICache` expire by wall clock; expired entries count as miss + eviction. |
| **Content stale detection** | `GitHubAPICache.CacheEntry.is_stale` compares multihash of validation fields when multiformats is available; otherwise TTL only. |
| **Invalidation APIs** | `invalidate` / `invalidate_pattern` / `clear` on API cache; `delete` / `clear` / `optimize` on `CacheManager`. |
| **Trust** | Caches are **untrusted performance layers**. Security-sensitive reads revalidate from source or recompute digests. |
| **Remote/P2P cache** | Legacy raw libp2p cache stream for GitHub API cache is **disabled** (`HAVE_LIBP2P = False`); distributed sharing must use an approved service path. |
| **Router cache** | Backend selection cache can serve a stale client if env changes without `clear_ipfs_backend_router_caches()`. |

### 8.4 Consistency and integrity

| Scenario | Expected consistency |
| --- | --- |
| Same CID, same profile, two backends | Bytes must match if both return success; discrepancy is a storage/corruption incident |
| Pin on backend A only | Backend B may still `cat` via network; pin is local retention |
| Cache hit after content mutation | Stale if key omitted digest; use content-hash keys or short TTL |
| Local IPLD mode vs online | Local CIDs computed with multiformats should match online `block_put` for same bytes/codec; mock test CIDs do not |
| Mock storage engine ids | `MockStorageManager` uses truncated SHA-256 hex item ids—not multiformats CIDs |
| CAR import then get | Blocks available by CID from cache/backend; roots list is not a receipt of semantic validation |

**Integrity checklist for high-assurance paths:**

1. Validate inbound CID profile.
2. Fetch bytes from preferred backend.
3. Recompute CID (or multihash) of bytes under the declared profile.
4. Compare; on mismatch fail closed.
5. Only then update trusted caches.

### 8.5 Identifiers, locations, indexes, receipts (backend view)

| Kind | Backend/cache interpretation |
| --- | --- |
| **Identifier** | CID / content_hash fields; primary lookup key for blocks |
| **Location** | Backend name, API multiaddr, `IPFS_HOST`, pin set membership, filesystem `base_dir`, gateway URL |
| **Index** | Search/vector/graph indexes pointing at CIDs; `IPLDStorage._block_index` relationship sets; **not** interchangeable with CID |
| **Receipt** | Pin operation result, cluster pin_content result, cache stats snapshots, install/ops receipts—evidence of process, not identity |

### 8.6 Public surfaces and env

| Surface | Examples |
| --- | --- |
| Python | `from ipfs_datasets_py import ipfs_backend_router as r`; `IPLDStorage`; `IPFSPinner`; `CacheManager` |
| MCP | `ipfs_tools` pin/get; storage tools; cluster tools over mock engine |
| Env | `IPFS_DATASETS_PY_IPFS_BACKEND`, `IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `IPFS_KIT_DISABLE`, `IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI`, `IPFS_HOST`, `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE`, `IPFS_DATASETS_PY_KUBO_CMD`, `IPFS_DATASETS_PY_IPFS_CACHE_DIR`, `IPFS_DATASETS_PY_ROUTER_CACHE`, auto-install flags for kit |
| Packaging | `ipld` extra; optional kit/accelerate integrations; `ipfshttpclient` when HTTP backend enabled |

## 9. Failure modes and fallbacks

| Failure | Detection | Visible behavior | Recovery |
| --- | --- | --- | --- |
| No backend / CLI missing | Resolution fails or CLI errors | RuntimeError / pin status error | Install Kubo or enable kit/HTTP; bootstrap kit if policy allows |
| Kit import fails | Exception in `_get_ipfs_kit_backend` | Fall through to next backend | Fix install; set force backend |
| HTTP API connect fails | Exception constructing client | Fall through | Check `IPFS_HOST` / daemon |
| Accelerate unavailable | Env off or import fail | Fall through to Kubo | Enable only when needed |
| `block_*` unsupported on accelerate | Explicit RuntimeError | Caller must choose another backend | Kit/HTTP/Kubo |
| Daemon offline mid-run | IPLD store/get exception | `_ipfs_failed=True`, local-only mode | `connect()`; restart daemon; CAR import |
| Pin path missing | `IPFSPinner` path check | `status=error` | Correct path |
| Cache expired / miss | TTL or not_found | `hit=False` | Recompute / refetch source |
| Stale API cache | Validation field multihash mismatch | Treat as miss | Refresh from GitHub API |
| Simulated CID offline | Backend returns `Qm{sha256…}` style | Operations may proceed in CI | Do not promote to protocol identity fields without `validate_cid` |
| Optional multiformats missing | Import flags false | Content-hash cache validation degrades to TTL; CID helpers fail at use | Install multiformats / `ipld` extra |
| Auto-install disabled offline | Env / network | Feature remains unavailable | Pre-provision wheelhouse |

**Feature degradation vs fail-closed trust:** missing pin service degrades
*availability*. Missing identity libraries for a protocol field fails that
feature. Authorization and proof never soft-allow because a cache hit or pin
succeeded ([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).

## 10. Optional dependencies

| Dependency / extra | Needed for | Without it |
| --- | --- | --- |
| `multiformats` | Portable CIDs, validation, content-hash cache keys | No production CIDs; TTL-only staleness |
| `ipld-car` / `libipld` | CAR encode/decode performance and export | CAR paths unavailable |
| `ipld-dag-pb` | Official DAG-PB | Local `dag_pb.py` fallback |
| `ipfs_kit_py` | Kit backend | Skip kit in resolution |
| `ipfs_accelerate_py` | Accelerate filesystem backend | Skip accelerate |
| `ipfshttpclient` | HTTP API backend | Skip HTTP |
| Kubo `ipfs` CLI | Default CLI backend | Need another backend or bootstrap kit |
| `cryptography` | Optional GitHub cache encryption | Encryption features off |

Lifecycle detail:
[DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md).

## 11. Offline behavior

| Mode | Behavior |
| --- | --- |
| **Hermetic import** | Package loads without contacting IPFS |
| **No daemon** | IPLD local-only block cache; CAR file interchange; mock storage engine for tests |
| **No network** | Auto-install must be off or wheelhouse-only; remote caches and pin services unavailable |
| **Offline read of known blocks** | Succeeds from `_block_cache`, disk cache, or imported CAR |
| **Offline pin** | Generally fails or is no-op depending on backend; local mock paths may still return structured results |
| **Offline identity** | Canonical bytes + multiformats still compute CIDs without network |

Offline does **not** change content identity. It only changes which **locations**
can resolve a CID.

## 12. Failure recovery runbook

1. **Identify layer:** identity (CID profile), transport (backend), retention
   (pin), or cache (TTL/stale).
2. **Validate the CID** if present on a contract surface.
3. **Clear stale router selection** if env changed:
   `clear_ipfs_backend_router_caches()`.
4. **Reconnect IPLD:** `IPLDStorage().connect()` after daemon restart.
5. **Re-import CAR** for air-gapped restore of block sets.
6. **Re-pin** only after integrity of bytes is confirmed.
7. **Invalidate application caches** that keyed without digests.
8. **Do not** “fix” integrity by writing a new mock id over a failed pin.

## 13. Extension points

1. **New IPFS backend:** implement `IPFSBackend`, `register_ipfs_backend(name, factory)`,
   document env flag and capability gaps (especially block API).
2. **New cache backend:** implement behind `CacheManager` or a dedicated module;
   document key schema, TTL, and trust (never claim cache = proof).
3. **New pin strategy:** extend `IPFSPinner` or cluster helpers; keep MCP tools thin.
4. **Tests:** backend resolution with env matrix; pin error paths; cache
   expiry/stale; offline IPLD local mode.
5. **Docs:** update this guide + content-addressing guide when boundaries move.

**Anti-patterns:**

- Business logic only in MCP wrappers.
- Using pin success as authorization.
- Caching policy decisions without binding digests of inputs.
- Forcing accelerate when IPLD `block_put` is required.
- Treating `MockStorageManager` item ids as multiformats CIDs.

## 14. Invariants

1. **Router selects locations; CIDs name content.**
2. **Pin is retention, not identity.**
3. **Caches are performance layers unless explicitly content-validated—and
   even then they are not receipts.**
4. **Indexes reference identifiers; they are not identifiers.**
5. **Optional backends degrade features; they do not rewrite identity rules.**
6. **Process injection (`set_default_ipfs_backend`, `RouterDeps`) is explicit
   and must not silently override forced provider names.**
7. **Simulated offline CIDs are not portable production identity.**
8. **Integrity-sensitive paths recompute digests after fetch.**
9. **Clear backend caches after configuration changes in long-lived processes.**
10. **Kinds of truth stay labeled** in APIs and docs (ADR-001).

## 15. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Pluggable backends | Avoid import-time kit; predictable CI via CLI default | `ipfs_backend_router` module doc |
| Identity vs location | Multi-backend retrieval without changing artifact ids | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Lazy optional stacks | Probe ≠ capability; feature vs trust | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Local IPLD fallback | Developers/tests progress without daemon | `IPLDStorage` |
| Disable raw P2P cache stream | Avoid unauthenticated cache poisoning surface | `caching/cache.py` |

## 16. Security, privacy, and trust boundaries

- Untrusted peers and gateways can serve wrong bytes for a CID only if the
  client **skips** digest verification—always recompute for high assurance.
- Cache poisoning: accept remote cache entries only through authenticated
  approved channels; local GitHub cache encryption is optional and not a
  substitute for TLS to GitHub.
- Pin services and cluster APIs are privileged operations; gate via product
  authz layers—not by CID possession.
- Secrets: do not pin or cache plaintext secrets under public CIDs.

## 17. Observability and operations

- Router and pinner log errors with backend context.
- Cache stats: hits, misses, evictions (`CacheManager.get_stats`,
  `GitHubAPICache.get_stats`).
- Cluster mock: `get_cluster_status` for tool demos.
- Operator knobs: env flags listed in §8.6; `IPFS_DATASETS_PY_IPFS_CACHE_DIR`
  for accelerate filesystem cache.

## 18. Validation

```bash
test -s docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md
test -s docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md
rg -n 'canonical|CID|CAR|cache|backend|integrity' \
  docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md \
  docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md

# Implementation anchors
rg -n 'def get_ipfs_backend|class IPFSBackend|_resolve_backend' \
  ipfs_datasets_py/ipfs_backend_router.py
rg -n 'class CacheManager|class GitHubAPICache' \
  ipfs_datasets_py/caching/cache_manager.py \
  ipfs_datasets_py/caching/cache.py
rg -n 'class IPFSPinner|class MockIPFSClusterService' \
  ipfs_datasets_py/core_operations/ipfs_pinner.py \
  ipfs_datasets_py/ipfs_cluster/cluster_engine.py
test -s ipfs_datasets_py/storage/storage_engine.py
```

**Limitations:** live multi-backend integration tests require daemons and
optional extras; mock cluster is not a substitute for production IPFS Cluster
verification.

## 19. Related documentation

| Document | Relationship |
| --- | --- |
| [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | Identity, codecs, CAR |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Identifier ≠ location/receipt |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional backend lifecycle |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | RouterDeps, install policy |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | kit / accelerate ownership |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Storage domain map |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flows that pin/store |

## 20. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide (`IPFSDOC-023`) |
