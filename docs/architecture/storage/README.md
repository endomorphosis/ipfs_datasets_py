# Storage and distribution architecture index

| Field | Value |
| --- | --- |
| Interface | `StorageArchitectureIndex@1` |
| Task | `IPFSDOC-026` |
| Status | `canonical` |
| Owner | architecture / storage domain |
| Source of truth | Canonical leaves under `docs/architecture/storage/`; `ipfs_datasets_py/{storage,caching,ipfs_backend_router,ipfs_cluster,p2p_networking,huggingface,voice,core_operations,processors/storage}/`; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §3–4; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) |
| Review cadence | after identity, backend router, pin/cluster, P2P, or release/publication surface changes |

> **Lifecycle:** This page is the **canonical routing hub** for storage,
> distribution, and immutable release. It does **not** replace leaf
> architecture guides. Prefer the leaves for contracts, failure modes, and
> extension detail. Session reports, migration plans, stub dumps under
> `docs/archived_stubs/storage/`, and completion summaries are **not**
> architecture authority.

## 1. Purpose

Route developers, operators, and agents to the right storage and distribution
documentation:

| Need | Go to |
| --- | --- |
| Content identity, CID profiles, IPLD blocks, CAR interchange | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) |
| Backend selection, pins, caches, offline recovery | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) |
| Peer workflows, transport handoffs, thin HF publish surface | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) |
| Immutable build → dry-run → approve → publish → load / canary / rollback | [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) |
| Domain ownership of storage vs neighbors | [DOMAIN_MAP.md](../DOMAIN_MAP.md) (Storage / release cluster) |
| Cross-domain hop language (emit CID → pin → distribute → release) | [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) |
| Identifier ≠ location ≠ index ≠ receipt | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Optional backend / libp2p / Hub extras | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Retained component paths and package anchors | §5 Component families (this page) + leaf component tables |
| API / MCP / CLI operator surfaces | §7.3 API, MCP, and operations |
| How to extend safely | §6 Extension recipes + leaf “Extension points” sections |
| Backend-specific, optional, compat, or historical material only | §5 status legend + §7.4–§7.5 (labeled; not sole architecture) |

**Effects of this index:** one entry point for storage and distribution without
rewriting the leaf guides. New code and docs should link here for orientation,
then drop into the owning leaf.

## 2. Audience

- **Primary:** developers and agents choosing where to implement or document
  content-addressed storage, backend I/O, peer distribution, or immutable
  release.
- **Secondary:** operators configuring pins, caches, cluster helpers, Hub
  publish, and degraded offline paths; architects placing new storage
  surfaces relative to processing, retrieval, and knowledge.

## 3. Scope and non-goals

### In scope

- Index of **canonical** storage / distribution / release architecture leaves.
- **Ownership** and **current / optional / backend-specific / compatibility /
  historical** status per storage family.
- Routes to retained component paths, API and MCP surfaces, operations guides,
  extension seams, and labeled non-authoritative material.
- Explicit honesty: mock cluster, simulated peer results, dry-run receipts, and
  accelerate/kit fallback `Qm…` strings are **not** distributed completion or
  portable content identity.

### Non-goals

- Full CID/IPLD/CAR algorithms → [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md).
- Full backend priority matrix, pin lifecycle, cache trust → [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md).
- Full peer/task/cluster/HF publication contracts → [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md).
- Full voice schema / quality gates / append-only release lifecycle → [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md).
- Vector ANN index engines and search ranking → retrieval architecture
  (`docs/architecture/retrieval/`).
- Formal IR identity, provers, UCAN/wallet policy bodies → logic / trust tracks.
- Hosting Kubo, IPFS Cluster, or Hugging Face Hub as a product deliverable of
  this repository.
- MCP transport and tool lifecycle framing → [architecture/mcp/](../mcp/).

## 4. Canonical storage guides

These four pages are the **architecture authority** for storage and
distribution under `docs/architecture/storage/`. All four have status
`canonical` as of last verification.

| Guide | Interface | Owns | Status |
| --- | --- | --- | --- |
| [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | `ContentAddressedStorageArchitecture@1` | Canonical bytes, CID profiles, IPLD block encode/decode, CAR export/import, identity vs location/index/receipt | **canonical** — identity model for the product |
| [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | `StorageCacheBackendArchitecture@1` | `IPFSBackend` resolution, kit/HTTP/accelerate/Kubo providers, pins, cluster *helpers*, multi-layer caches, offline recovery | **canonical** — location and retention; not identity |
| [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | `P2PDistributionArchitecture@1` | Peer discovery/registry, workflow/task scheduling, transport handoffs, cluster retention vs single-node pin, thin HF publication surface, stub/mock labeling | **canonical** — distribution and work movement |
| [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) | `ImmutableDatasetReleaseLifecycle@1` | Voice schema → normalize/quarantine → quality gates → offline materialize → byte-identical shards → dry-run / approve / append-only publish → pinned load / canary / rollback | **canonical** — bespoke immutable release plane |

```text
                    ┌──────────────────────────────────────┐
                    │  docs/architecture/storage/          │
                    │  README.md  (this index)             │
                    └──────────────────┬───────────────────┘
         ┌───────────────┬─────────────┼─────────────┬────────────────┐
         ▼               ▼             ▼             ▼                │
 CONTENT_ADDRESSING_  STORAGE_CACHING_  P2P_AND_   IMMUTABLE_DATASET_ │
 AND_IPLD.md          AND_BACKENDS.md  PUBLICATION RELEASES.md        │
 (identity / IPLD)    (where / pin /   .md         (build → publish   │
                       cache)          (peers +     → load)           │
                                       thin publish)                  │
         └───────────────┴─────────────┴─────────────┴────────────────┘
```

Cross-links among leaves: identity owns *what* a CID is; backends own *where*
bytes live and how pins/caches work; P2P owns *how work and content move*
across peers and the thin publish surface; releases own the *product lifecycle*
from offline build through approved Hub promotion and pinned load.

**Kinds of truth (do not collapse):** content **CID**, backend **location**,
**pin** membership, peer/connection **id**, dry-run **receipt**, Hub **commit
SHA**, runtime **pointer** canary, GraphRAG **index_cid**. See
[ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md).

## 5. Component families: ownership and status

**Product cluster (DOMAIN_MAP):** `storage`, `caching`, `ipfs_cluster`,
`p2p_networking`, `huggingface`, `voice` → this directory
([DOMAIN_MAP.md](../DOMAIN_MAP.md) §3). Related IPLD helpers also live under
`processors/storage` and `processors/serialization`; processing may **emit**
CIDs, but storage architecture owns backend and identity contracts.

MCP tools under
`mcp_server/tools/{ipfs_tools,storage_tools,ipfs_cluster_tools,p2p_tools,p2p_workflow_tools,cache_tools,dataset_tools}/`
and CLI groups (`ipfs-datasets p2p …`, pin/storage helpers) are **thin
wrappers**; algorithms stay in domain packages.

Status legend:

| Status | Meaning |
| --- | --- |
| **canonical** | Preferred import / design for new work |
| **compat** | Supported transitional surface; prefer canonical when writing new code |
| **optional** | Requires extras, host binaries, secrets, daemons, or injected clients |
| **backend-specific** | Behavior or capability depends on which `IPFSBackend` provider is selected |
| **deprecated** | Still importable with warnings or re-exports; do not extend |
| **historical** | Docs or paths describing past plans/migrations/stubs; not live architecture |
| **mock / stub** | Explicit non-production path; unit green ≠ distributed completion |

### 5.1 Family matrix

| Family | Canonical path(s) | Optional / backend-specific / compat / mock | Architecture leaf | Notes |
| --- | --- | --- | --- | --- |
| **CID helpers & profiles** | `utils/cid_utils.py`; `logic/ipld_cid.py`; `logic/ir_core/canonical.py` (`ir-canonical-json-v1`) | Multiformats **optional** for full CIDv1; IR profile must not require multiformats | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | Fail closed on profile mismatch; no invented “hash fields” |
| **IPLD block storage** | `processors/storage/ipld/storage.py` (`IPLDStorage`) | Online put/get via router **optional**; local `_block_cache` always process-local | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | Identity + block API; not general app cache |
| **CAR interchange** | `IPLDStorage` export/import; `processors/serialization/car_conversion.py` | `ipld-car` / related extras **optional** | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | Offline interchange of roots + blocks |
| **Storage engine facade** | `storage/storage_engine.py` | `MockStorageManager` for tests/dev | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Enums/dataclasses; **not** production IPLD layer |
| **Backend router** | `ipfs_backend_router.py`; `router_deps.py` | Provider stack **optional** per env; resolution **backend-specific** | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Stable `get_ipfs_backend` / add / cat / pin / block_* |
| **Kubo CLI backend** | router Kubo path (`IPFS_DATASETS_PY_KUBO_CMD`) | Host `ipfs` binary **optional** | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | **backend-specific** default fallback when enabled |
| **HTTP API backend** | `ipfshttpclient` via env flags | Extra + live daemon **optional** | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | **backend-specific** |
| **ipfs_kit_py backend** | kit integration via `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Submodule/extra **optional**; simulated IDs when offline | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | **backend-specific**; simulated `Qm…` ≠ portable CIDv1 |
| **ipfs_accelerate_py backend** | accelerate path via env flag | Extra **optional**; limited block API | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | **backend-specific**; prefer kit/HTTP/Kubo for true IPLD blocks |
| **Pinning** | `core_operations/ipfs_pinner.py` (`IPFSPinner`); router `pin`/`unpin` | Real pin needs live backend; some dict paths **mock** for tests | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Pin = retention/location, not identity |
| **IPFS cluster helpers** | `ipfs_cluster/cluster_engine.py` | `MockIPFSClusterService` is **mock** domain logic | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md), [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Not a full Cluster operator product |
| **Application caches** | `caching/cache_manager.py`, `caching/cache.py`, `caching/cache_engine.py` | Multiformats for content-validated keys **optional** | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Performance/policy; not content identity by default |
| **Distributed / task P2P cache** | `caching/distributed_cache.py`, `router_remote_cache.py`, `task_p2p_cache.py` | Peer/remote paths **optional**; raw stream protocols may be disabled | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md), [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Do not treat peer gossip as integrity root |
| **P2P networking package** | `p2p_networking/` (peer registry, connectivity, workflow scheduler, engines) | py-libp2p / MCP++ / `gh` cache paths **optional**; degrades without stack | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Label stub vs live transport |
| **P2P task / workflow engines** | `peer_engine.py`, `taskqueue_engine.py`, `workflow_engine.py` | MCP++ / accelerate wrappers **optional** | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Degraded responses must not invent completion |
| **Hugging Face publication (thin)** | `huggingface/publisher.py` (plan / dry-run / commit / verify) | Hub token + `HfApi` **optional**; default dry-run | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md), [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) | Append-only; autonomous workers stop at dry-run |
| **HF release helpers** | `huggingface/{release,repository,snapshot,bucket}.py` | `pyarrow` / `huggingface_hub` / `datasets` **optional** | [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) | Snapshot cache identity aliases are **compat** wire names |
| **Voice immutable release plane** | `voice/` (schema, normalize, graphrag, materialize, audio_quality, hf_release, release_loader, workset) | TTS/ASR executors injected **optional**; remote write approval-gated | [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) | Reference domain lifecycle for immutable releases |
| **Dataset manager API** | `dataset_manager.py`, `ipfs_datasets.py` | Uses storage/IPFS helpers; not backend authority | [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Dataset ops surface; route identity/backends to leaves |
| **MCP / CLI thin surfaces** | `mcp_server/tools/{ipfs_tools,storage_tools,ipfs_cluster_tools,p2p_tools,p2p_workflow_tools,cache_tools}/`; CLI `p2p` group | Tool availability **optional** by install | §7.3; leaf inbound sections | No business logic only in tool modules |

### 5.2 Ownership boundaries (summary)

| Owns (storage / distribution / release) | Does not own |
| --- | --- |
| Content identity rules (CID/IPLD/CAR profiles) | Vector ANN layout and query ranking |
| Backend selection, pin retention, application caches | Full Kubo / Cluster / Hub hosting products |
| Peer discovery, workflow/task distribution contracts | GitHub Actions product runtime or billing |
| Immutable release build/publish/load lifecycle (voice + HF helpers) | Treating `main` / `latest` as production identity |
| Labeling mock, stub, dry-run, and simulated success | Proof/authorization kernels (they *consume* digests) |
| Provenance-friendly storage of lineage **bytes** when asked | Declaring semantic truth from store success alone |

**Inbound:** Python API, MCP IPFS/storage/P2P/cluster/cache tools, CLI (`p2p`,
pin/storage helpers), release builders, GraphRAG restore loaders, offline
validation harnesses, autonomous agents (through **dry-run** only for publish).

**Outbound:** optional multiformats/IPLD/CAR stacks; Kubo/`ipfshttpclient`/
kit/accelerate backends; optional py-libp2p and MCP++; optional
`huggingface_hub` / `datasets` / `pyarrow`; local disk for CAR and cache dirs.

## 6. Extension recipes (where to implement)

Do **not** put new storage business logic only in MCP tool modules. Prefer
domain packages, then thin wrappers.

| Extension | Recipe summary | Detail |
| --- | --- | --- |
| New CID / canonical profile | Deterministic bytes → validated CIDv1; document profile id; fail closed on mismatch | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) |
| New IPLD codec or CAR path | Encode/decode under allowlisted codecs; round-trip tests; optional dep guards | [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) |
| New IPFS backend provider | Implement `IPFSBackend`; register in router resolution with env flags; document capability gaps | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) |
| New pin orchestration | Domain pin helper over router; never invent CID from pin success | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) |
| New application cache | `CacheManager` namespace + TTL; content-validated keys when multiformats present; do not redefine identity | [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) |
| New P2P workflow / peer surface | Prefer `p2p_networking` engines + explicit degraded modes; label mock discovery | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) |
| New publication surface | Plan → dry-run receipt → human approval → append-only commit → verify; agents stop at dry-run | [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md), [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) |
| New immutable dataset domain | Schema + normalize/quarantine + offline materialize + shard digests/CIDs + HF helpers; no parallel identity fields | [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) |
| Optional dependency lifecycle | Lazy import; feature degrade OK; inventing success not OK | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

**Anti-patterns (all leaves agree):** collapsing CID / path / pin / peer id /
commit SHA / dry-run receipt into one “id”; treating mock cluster or simulated
`Qm…` as portable identity; autonomous remote write without approval; mutable
Hub refs (`main`/`latest`) as release pins; business logic only in MCP files;
assuming missing extras mean undocumented architecture rather than unprovisioned
capability.

## 7. Documentation routes by authority class

### 7.1 Canonical architecture (preferred)

| Document | Role |
| --- | --- |
| **This index** | Routing, family status, extension map |
| [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | Identity, IPLD, CAR |
| [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Routers, pins, caches, offline recovery |
| [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Peers, tasks, distribution, thin publish |
| [IMMUTABLE_DATASET_RELEASES.md](IMMUTABLE_DATASET_RELEASES.md) | Immutable build / publish / load lifecycle |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Product domain map (storage/release cluster) |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain hops |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Kinds of truth |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional capability lifecycle |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Feature degrade vs trust fail-closed |

### 7.2 Retained component references (implementation anchors)

Use these live package paths as **component references**. Prefer architecture
leaves when contracts conflict with comments or older READMEs.

| Area | Paths |
| --- | --- |
| Identity / IPLD | `ipfs_datasets_py/utils/cid_utils.py`, `logic/ipld_cid.py`, `logic/ir_core/canonical.py`, `processors/storage/ipld/`, `processors/serialization/car_conversion.py` |
| Router / backends | `ipfs_datasets_py/ipfs_backend_router.py`, `router_deps.py` |
| Storage facade | `ipfs_datasets_py/storage/storage_engine.py` |
| Pins / core ops | `ipfs_datasets_py/core_operations/ipfs_pinner.py` (+ related loader/saver/getter under `core_operations/`) |
| Cluster helpers | `ipfs_datasets_py/ipfs_cluster/cluster_engine.py` |
| Caches | `ipfs_datasets_py/caching/` (`cache_manager.py`, `cache.py`, `distributed_cache.py`, `task_p2p_cache.py`, …) |
| P2P | `ipfs_datasets_py/p2p_networking/` |
| HF helpers | `ipfs_datasets_py/huggingface/` |
| Voice release | `ipfs_datasets_py/voice/` |
| Dataset API surface | `ipfs_datasets_py/dataset_manager.py`, `ipfs_datasets.py` |

### 7.3 API, MCP, and operations

| Surface | Location | Role | Label |
| --- | --- | --- | --- |
| Core operations API notes | [docs/api/CORE_OPERATIONS_API.md](../../api/CORE_OPERATIONS_API.md) | Loader/saver/pinner/getter style API exposition | **API reference** — verify against current modules |
| Router ownership guide | [docs/guides/ROUTER_OWNERSHIP.md](../../guides/ROUTER_OWNERSHIP.md) | Shared router / deps ownership narrative | **maintained guide** (not leaf replacement) |
| Kit / accelerate integration | [IPFS_KIT_INTEGRATION.md](../../guides/IPFS_KIT_INTEGRATION.md), [IPFS_ACCELERATE_INTEGRATION.md](../../guides/IPFS_ACCELERATE_INTEGRATION.md), [IPFS_KIT_PY_SUBMODULE_INTEGRATION.md](../../guides/IPFS_KIT_PY_SUBMODULE_INTEGRATION.md) | Operator/integration detail for **backend-specific** stacks | **optional / integration** |
| Distributed cache guide | [DISTRIBUTED_CACHE.md](../../guides/DISTRIBUTED_CACHE.md) | Application distributed-cache exposition | **maintained guide** — trust rules still from storage leaves |
| P2P cache operator notes | `docs/guides/p2p/P2P_CACHE_*.md` | Encryption, quick ref, integration narratives | **operator / mixed** — prefer architecture leaf for authority |
| MCP IPFS tools | `ipfs_datasets_py/mcp_server/tools/ipfs_tools/` | Thin pin/add/cat style tools | **MCP shim** |
| MCP storage tools | `…/storage_tools/` | Thin storage wrappers | **MCP shim** |
| MCP cluster tools | `…/ipfs_cluster_tools/` | Cluster helper exposure | **MCP shim** — mock vs live honesty |
| MCP P2P tools | `…/p2p_tools/`, `…/p2p_workflow_tools/` | Peer/workflow tool surface | **MCP shim** — optional stack |
| MCP cache tools | `…/cache_tools/` | Cache inspection/control wrappers | **MCP shim** |
| CLI | `ipfs_datasets_cli.py` (`p2p` group and storage-related commands) | Operator entrypoints | **CLI** |
| Dependency / init | [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports, extras, RouterDeps | **cross-cutting ops** |
| Integration boundaries | [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | kit / accelerate / submodule ownership | **cross-cutting ops** |
| Future ops runbooks | `docs/guides/operations/` (when published: deployment, performance, diagnostics) | Host deployment and recovery | **planned ops track** — do not invent content here |

Package-local docstrings and package READMEs under the paths in §7.2 are
implementation-level detail. “PROJECT_COMPLETE” and session completion reports
are **historical session evidence**, not preferred architecture.

### 7.4 Backend-specific and optional material (labeled)

| Material | Label | Use for |
| --- | --- | --- |
| Kit / accelerate / HTTP API / Kubo capability matrices in leaves | **backend-specific** | Choosing a provider; capability gaps (e.g. accelerate block API limits) |
| Env flags (`IPFS_DATASETS_PY_*`, `IPFS_HOST`, kit disable) | **optional configuration** | Local/dev/prod enablement; not identity |
| Multiformats, ipld-car, libp2p, pyarrow, huggingface_hub extras | **optional dependencies** | Install gates; missing extra ≠ missing architecture |
| Hub tokens, `gh` for GHA peer registry, live daemons | **optional secrets / host services** | Live publish and multi-peer; offline remains valid for dry-run and local CAR |
| Simulated kit/accelerate `Qm…` identifiers | **fallback / non-portable** | Offline CI only; do not write into protocol identity fields without validation |

### 7.5 Historical migrations and stubs (do not treat as current architecture)

Use only to understand **how** the tree got here or to interpret old paths.
Always re-verify against the **canonical** leaves and live code.

| Document / path | Topic | Label |
| --- | --- | --- |
| `docs/archived_stubs/storage/` (e.g. `ipld/storage_stubs.md`) | Stub dumps of storage surfaces | **historical / archive** |
| `docs/implementation/plans/p2p_workflow_scheduler.md` | P2P scheduler plan/usage notes | **historical plan** — [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) is architecture authority |
| `docs/implementation/plans/p2p_cache_system.md` | P2P cache plan notes | **historical plan** |
| `docs/guides/p2p/P2P_CACHE_FINAL_STATUS.md`, `*_TEST_REPORT.md`, `*_FINAL_TEST_REPORT.md` | Session/status reports | **historical evidence** |
| Root/guide completion slogans and fixed “N backends” marketing counts | Inventory snapshots | **historical** — do not use as current inventory authority |
| SkillCenter → Hugging Face snapshot type aliases | Wire **compat** names retained under HF package | **compat** (current) but not a second identity model — see release leaf |

## 8. Decision guide (quick chooser)

```text
What are you doing?
│
├─ Name, hash, encode, or interchange content (CID / IPLD / CAR)?
│    → CONTENT_ADDRESSING_AND_IPLD.md  (+ ADR-001)
│
├─ Choose a backend, pin content, or reason about caches / offline recovery?
│    → STORAGE_CACHING_AND_BACKENDS.md
│    → which provider?  read backend-specific capability gaps
│    → missing kit/HTTP/Kubo?  optional deps + INTEGRATION_BOUNDARIES
│
├─ Move work or content across peers, cluster retention, or thin Hub publish?
│    → P2P_AND_PUBLICATION.md
│    → stub/mock discovery or mock cluster?  not distributed completion
│
├─ Build, gate, dry-run, approve, publish, load, canary, or rollback a release?
│    → IMMUTABLE_DATASET_RELEASES.md
│    → agents: stop at dry-run; mutable refs rejected at load
│
├─ Add a new storage capability?
│    → §6 Extension recipes → owning leaf
│
├─ Only reading an old stub, status report, or migration plan?
│    → §7.5 historical, then re-check canonical leaf
│
└─ Cross-domain “where does the artifact go next?”
     → END_TO_END_DATA_FLOW.md, then processing / retrieval / knowledge / logic leaves
```

## 9. Related architecture and governance

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture documentation hub |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context (voice release placement) |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | kit / accelerate / submodule boundaries |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | CLI/module entry points |
| [processing/README.md](../processing/README.md) | Processing index (may emit CIDs; does not own backends) |
| [retrieval/](../retrieval/) | Embeddings / vector stores / search (indexes *reference* content) |
| [knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md](../knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md) | GraphRAG lifecycle consuming CIDs |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence precedence |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) | Doc IA |

## 10. Validation

Bounded offline checks for this index:

```bash
# Declared output present and keyword coverage
test -s docs/architecture/storage/README.md
rg -n 'CONTENT_ADDRESSING_AND_IPLD|STORAGE_CACHING_AND_BACKENDS|P2P_AND_PUBLICATION|IMMUTABLE_DATASET_RELEASES' \
  docs/architecture/storage/README.md

# Canonical leaves still present
test -s docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md
test -s docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md
test -s docs/architecture/storage/P2P_AND_PUBLICATION.md
test -s docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md

# Package anchors for major families
test -s ipfs_datasets_py/ipfs_backend_router.py
test -s ipfs_datasets_py/storage/storage_engine.py
test -d ipfs_datasets_py/caching
test -d ipfs_datasets_py/ipfs_cluster
test -d ipfs_datasets_py/p2p_networking
test -d ipfs_datasets_py/huggingface
test -d ipfs_datasets_py/voice
test -d ipfs_datasets_py/processors/storage
test -d ipfs_datasets_py/core_operations
```

Known limits: live multi-backend, multi-peer, IPFS Cluster consensus, and Hub
publish paths are environment- and secret-gated. Optional extras
(multiformats, ipld-car, libp2p, pyarrow, huggingface_hub) may be absent.
This index only proves **routing, ownership language, and status labeling**,
not full distributed runtime proof. A green mock pin or dry-run receipt is not
a published immutable release.

## 11. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial **canonical** storage and distribution architecture index for `IPFSDOC-026` / `StorageArchitectureIndex@1` |
