# Content addressing and IPLD

| Field | Value |
| --- | --- |
| Interface | `ContentAddressedStorageArchitecture@1` |
| Task | `IPFSDOC-023` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/utils/cid_utils.py`; `ipfs_datasets_py/logic/ipld_cid.py`; `ipfs_datasets_py/logic/ir_core/canonical.py`; `ipfs_datasets_py/processors/storage/ipld/`; `ipfs_datasets_py/processors/serialization/car_conversion.py`; `ipfs_datasets_py/ipfs_backend_router.py`; packaging extras (`ipld`, multiformats); [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Review cadence | after CID helper, IPLD codec, or CAR packaging changes |

> **Lifecycle:** Status is `canonical` for the identity and IPLD representation
> model documented here. Backend selection, pin lifecycle, and general-purpose
> caches are owned by
> [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md).

## 1. Purpose

This guide answers: **how content is identified, encoded as IPLD blocks, and
packaged for interchange (CAR) in `ipfs_datasets_py`.** It defines canonical
bytes, CID profiles, codecs, and the hard distinction among **identifiers**,
**locations**, **indexes**, and **receipts**. Callers that store or retrieve by
CID use this model; they do not invent parallel “hash fields.”

## 2. Audience

- **Primary:** architects and developers implementing or reviewing
  content-addressed storage, IR/policy artifacts, dataset serialization, and
  GraphRAG IPLD graphs.
- **Secondary:** agents and operators interpreting CIDs in logs, MCP tool
  results, and provenance chains.

## 3. Scope and non-goals

### In scope

- Canonical byte encoding profiles and when each applies.
- CID construction and validation (CIDv1, multihash, codec allowlists).
- IPLD block storage (`IPLDStorage`), DAG-PB linking, optimized batch codecs.
- CAR export/import and format interchange (Parquet/Arrow → CAR).
- Integrity rules: recompute, validate, fail closed on profile mismatch.
- Optional multiformats / IPLD / CAR dependencies and offline local-block mode.
- Kinds of truth: identifier vs location vs index vs receipt vs authorization
  vs proof ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).

### Non-goals

- Router backend priority, pin APIs, cluster replication, and general cache
  managers — see [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md).
- P2P task workflows, Hugging Face publication, IPNS naming as product
  distribution — planned sibling guide `P2P_AND_PUBLICATION.md`.
- Vector *index* semantics and ANN query contracts — `vector_stores` /
  retrieval architecture.
- Authorization, UCAN, or solver proof kernels — they *consume* digests;
  they are not content identity.
- Changing production code as part of this documentation task.

## 4. Context

IPFS Datasets Python is content-addressed by design: dataset bytes, processor
outputs, IR documents, policy packets, and lineage records cross process and
network boundaries. Without a shared identity model:

1. Two JSON encodings of the same logical object hash differently.
2. Paths, gateway URLs, and pin-set membership get mistaken for durable identity.
3. CIDs, pins, provenance rows, and policy receipts collapse into one “id” in
   logs and agent prompts.
4. Optional multiformats/IPLD extras tempt call sites to invent non-CID strings
   labeled as CIDs.

This product already implements the answer in layers:

| Layer | Role |
| --- | --- |
| **Canonical bytes** | Deterministic encoding before any hash |
| **CID** | Portable identifier for those bytes (or IPLD block) under a codec/multihash |
| **IPLD storage** | Block put/get, linking, schema validation, local block cache |
| **CAR** | Portable archive of roots + blocks for interchange offline or between nodes |
| **Backend router** | *Where* blocks live (location/transport)—not identity |

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Canonical byte profiles and CID helpers | Pin retention policy and cluster consensus |
| IPLD block encode/decode contracts | HTTP/Kubo/kit daemon lifecycle |
| CAR encode/decode path contracts | ANN/vector index layout |
| Local block cache *inside* `IPLDStorage` (process memory) | General `CacheManager` / GitHub API cache |
| Integrity of content identity rules | Authorization or proof of semantic claims |

**Inbound callers:** dataset serialization, provenance-enhanced storage,
GraphRAG/knowledge-graph builders, IR/policy artifact writers, MCP
storage/IPFS tools (thin wrappers), benchmarks that mirror the byte contract.

**Outbound dependencies:** `multiformats` (CID + multihash); optional
`ipld-car`, `libipld`, `ipld-dag-pb`, `dag-cbor`; `ipfs_backend_router` for
networked put/get; local filesystem for CAR paths.

**Authority notes:** Content identity is **not** location, receipt,
authorization, or proof. Tests, schemas, and the helpers cited as source of
truth outrank narrative docs
([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| CID + canonical JSON helpers | `ipfs_datasets_py/utils/cid_utils.py` | Preferred general helpers: `canonical_json_bytes`, `canonical_dag_json_bytes`, `cid_for_*`, `validate_cid` |
| Profile D policy CIDs | `ipfs_datasets_py/logic/ipld_cid.py` | CIDv1 + `dag-json` + `sha2-256` for Helia/Kubo-aligned policy blocks |
| IR canonical profile | `ipfs_datasets_py/logic/ir_core/canonical.py` | `ir-canonical-json-v1` without optional deps |
| Benchmark bridge | `benchmarks/logic_pipeline/content_addressing.py` | Same multiformats contract, hermetic import |
| IPLD storage | `ipfs_datasets_py/processors/storage/ipld/storage.py` | `IPLDStorage` singleton: store/get, JSON blocks, CAR, batch |
| DAG-PB | `ipfs_datasets_py/processors/storage/ipld/dag_pb.py` | Linkable DAG nodes; fallback when `ipld_dag_pb` missing |
| Optimized codec | `ipfs_datasets_py/processors/storage/ipld/optimized_codec.py` | Batch encode/decode, encoder cache stats |
| Knowledge graph (IPLD) | `ipfs_datasets_py/processors/storage/ipld/knowledge_graph.py` | Entity/relationship graphs as linked IPLD |
| Vector store (IPLD) | `ipfs_datasets_py/processors/storage/ipld/vector_store.py` (+ `vector_stores`) | Embeddings under IPLD; index is not the CID |
| CAR / interchange | `ipfs_datasets_py/processors/serialization/car_conversion.py` | Arrow/Parquet/HF → CAR via `IPLDStorage` |
| Format converter | `ipfs_datasets_py/utils/data_format_converter.py` | Includes `car` among supported formats |
| Backend router | `ipfs_datasets_py/ipfs_backend_router.py` | Transport for `block_put` / `block_get` / `cat` / pin |
| Thin storage engine | `ipfs_datasets_py/storage/storage_engine.py` | Enum/dataclass facade + mock manager (not the IPLD core) |

```text
Caller (API / MCP / CLI)
   |
   v
canonical bytes (named profile)
   |
   v
CID (CIDv1 / codec / multihash)
   |
   +--> IPLDStorage.store / store_json / store_batch
   |         |
   |         +--> local _block_cache
   |         +--> ipfs_backend_router.block_put (if online)
   |
   +--> export_to_car / DataInterchangeUtils  -->  .car file
   |
   v
retrieve: get / get_json / import_from_car  (verify by recomputing CID when required)
```

## 7. End-to-end flow

### 7.1 Happy path — structured object to CID to block

1. Choose an **encoding profile** (exact raw bytes, fail-closed DAG-JSON,
   legacy sorted JSON, or `ir-canonical-json-v1`).
2. Produce **canonical bytes** with that profile’s rules.
3. Compute **CID** (`cid_for_bytes` / `cid_for_dag_json` / Profile D
   `dag_json_cid` / IR-specific assignment after IR canonicalization).
4. Persist the block: `IPLDStorage.store` / `store_json`, or router
   `block_put` / `add_bytes`.
5. Optionally **pin** (availability policy — not identity).
6. Optionally **export CAR** for offline transfer or release packaging.
7. Record **provenance** that *references* the CID; do not treat the
   provenance row id as the content id.

### 7.2 Happy path — CAR round-trip

1. Collect root CIDs and ensure all dependent blocks are in cache or fetchable.
2. `export_to_car` / `export_to_car_stream` encodes roots + blocks (`ipld_car`).
3. Transfer the `.car` file (filesystem, release artifact, peer path).
4. `import_from_car` / stream import restores blocks into cache and optional
   backend; returns root CIDs.
5. Callers re-`get` by CID; integrity is the CID of retrieved bytes matching
   expectation.

### 7.3 Sequence (current behavior)

```text
Object  --profile-->  canonical_bytes  --multihash-->  CID
CID + bytes  --store-->  block (local cache ± IPFS)
roots + blocks  --CAR encode-->  file
file  --CAR decode-->  blocks  --get(CID)-->  bytes
bytes  --same profile-->  recomputed CID  (integrity check)
```

### 7.4 Initialization and lifecycle

- `IPLDStorage` is a **process singleton** (`__new__`); `base_dir` and
  `ipfs_api` configure local temp space and intended daemon multiaddr.
- Router availability is best-effort: `_ipfs_enabled` / `_ipfs_failed` gates
  remote put/get; `connect()` re-enables after failure.
- Multiformats / CAR packages load at use time; missing extras do not redefine
  identity ([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).

## 8. Contracts

### 8.1 Canonical bytes

| Profile | Entry points | Contract summary | Prefer for |
| --- | --- | --- | --- |
| **Exact bytes** | `cid_for_bytes(data, codec="raw")` | Hash the given `bytes` as-is; codec `raw` | Files, opaque blobs, pre-encoded blocks |
| **Strict DAG-JSON** | `canonical_dag_json_bytes`, `cid_for_dag_json` | Sorted keys, compact separators, UTF-8, `allow_nan=False`; rejects non-JSON types and non-finite floats; codec `dag-json` | New protocol / receipt / policy objects |
| **Legacy sorted JSON** | `canonical_json_bytes`, `cid_for_obj` | Sorted keys, compact separators; `default=repr` for non-JSON (less strict) | Existing call sites already on this contract |
| **Profile D DAG-JSON** | `logic.ipld_cid.canonical_dag_json`, `dag_json_cid` | Sorted keys, compact separators, `ensure_ascii=True`; CIDv1 `dag-json` `sha2-256` | Shared policy artifacts Helia/Kubo can store identically |
| **IR v1** | `ir-canonical-json-v1` in `logic.ir_core.canonical` | NFC text, sorted keys, finite decimals, set/multiset rules; **no optional deps** | Shared IR documents before CID assignment |

**Rule:** Changing separators, key order, Unicode normalization, codec,
multihash, or CID version **changes identity**. Treat that as a profile
version bump or explicit migration—not a silent refactor.

### 8.2 CID profiles

| Parameter | Default for new artifacts | Notes |
| --- | --- | --- |
| CID version | `1` | CIDv0 may appear from some IPFS `add` paths; validate before treating as protocol fields |
| Multibase | lowercase `base32` | `validate_cid` requires lowercase and matching base |
| Multihash | `sha2-256` | Other algorithms need an explicit allowlist and documentation |
| Codec | `raw` or `dag-json` | Linked structures use `dag-pb` when encoded as DAG nodes |

**Validation:** inbound contract fields that claim to be CIDs must pass
`validate_cid` (or an equivalently strict allowlist). Do not accept “looks
like a multiformat string.”

**Simulated / fallback identifiers:** when multiformats or backends are
absent, some paths emit local or mock handles (e.g. truncated digests, test
CIDs, accelerate simulated `Qm…` strings). Those are **availability
fallbacks**, not portable production CIDs. Never label them as validated
multiformats CIDs in trust-sensitive surfaces.

### 8.3 IPLD and CAR codecs

| Codec / format | Use | Implementation notes |
| --- | --- | --- |
| **raw** | Opaque block bytes | Default for unlinked `IPLDStorage.store(data)` |
| **dag-json** | Structured JSON IPLD data model | Preferred for new protocol objects (`cid_for_dag_json`) |
| **dag-pb** | Linked graphs (data + named links) | `create_dag_node` / `ipld_dag_pb` when available |
| **dag-cbor** | Optional CBOR IPLD | Cataloged under `ipld` extra (`libipld`); not the default helper path |
| **CAR (v1 path via `ipld_car`)** | Archive of roots + blocks | `export_to_car` / `import_from_car`; pure-Python encode required for save; `libipld` may accelerate decode |

CAR path safety: `DataInterchangeUtils._validate_car_path` confines export
paths to `IPFS_DATASETS_SAFE_ROOT` or the process CWD to reduce path-traversal
risks.

### 8.4 Identifiers, locations, indexes, and receipts

This table is normative for storage documentation and agent behavior:

| Kind | What it answers | Examples in this tree | What it is **not** |
| --- | --- | --- | --- |
| **Identifier (CID / content digest)** | *What* are the canonical bytes (under a profile)? | Output of `cid_for_*`, `validate_cid`, IPLD block CIDs | Location; pin status; authorization; proof |
| **Location** | *Where* can bytes be fetched *now*? | Kubo API multiaddr, gateway URL, filesystem path, `base_dir`, pin set on a node, router backend name | Content identity |
| **Index** | *How* do I search or navigate structure without loading every block? | Vector ANN indexes, graph adjacency indexes, `_block_index` relationship sets, search inverted indexes | The content id of the payload; proof of correctness |
| **Receipt** | *Did* a process run under stated inputs/outputs? | Policy admit receipts, benchmark receipts, install receipts, audit events | Content identity; permission to perform new side effects |
| **Provenance / lineage** | *How* was this produced? | `ProvenanceManager` SOURCE/TRANSFORM/MERGE graphs; optional IPLD-stored lineage | Substitute for byte equality |
| **Authorization / proof** | *May* this act? / *Is* this claim verified? | UCAN/policy gates; solver/ZKP kernel receipts | Established by holding a CID alone |

**Indexes vs identifiers:** an embedding vector store or GraphRAG index may
*point at* CIDs. Rebuilding the index does not change content identity;
mutating bytes without a new CID is a bug.

### 8.5 Public surfaces

- **Python API:** `ipfs_datasets_py.utils.cid_utils`;
  `ipfs_datasets_py.logic.ipld_cid`;
  `ipfs_datasets_py.processors.storage.ipld` (`IPLDStorage`, codecs, KG);
  `ipfs_datasets_py.processors.serialization.car_conversion`.
- **MCP / CLI:** IPFS and storage tools wrap pin/get/store; domain logic
  remains in the modules above (thin-wrapper rule).
- **Packaging extras:** `ipld` → `libipld`, `ipld-car`, `ipld-dag-pb`,
  `dag-cbor`, `multiformats` (see `dependency_catalog` / `pyproject.toml`).
- **Env (identity-adjacent):** `IPFS_DATASETS_SAFE_ROOT` for CAR path root;
  router env vars affect *location* only (see backends guide).

### 8.6 Persistence and integrity

| Guarantee | Meaning |
| --- | --- |
| Same profile + same logical object → same bytes → same CID | Core identity invariant |
| CID does not imply pinned or online | Availability is orthogonal |
| Local block cache is not a trust root | Cache can be wrong if fed non-validated bytes; re-hash when integrity matters |
| CAR import restores blocks by CID | Roots list is not a proof of semantic correctness |
| Provenance / receipts reference CIDs | They do not replace digests |

## 9. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| `multiformats` missing | ImportError on CID helpers | Features requiring CIDs fail at use | No synthetic production CIDs; local test handles only if clearly non-canonical |
| Non-JSON / NaN under DAG-JSON profile | `ValueError` / `TypeError` in `_validate_dag_json_value` | Store/CID aborted | Normalize or choose legacy profile deliberately |
| Invalid CID string on contract field | `validate_cid` raises | Reject input | Do not “fix” by string shape alone |
| IPFS daemon / router down | Exception in `block_put`/`block_get` | `IPLDStorage` sets `_ipfs_failed`, logs warning | Local-only mode: blocks in `_block_cache` with computed CID when multiformats present |
| Local-only get of unknown CID | Cache miss | `ValueError` (block not found) | Import CAR or reconnect via `connect()` |
| `ipld_car` missing | Import flag `HAVE_IPLD_CAR` | CAR export/import unavailable | Install `ipld` extra; do not write fake CAR files |
| CAR path outside safe root | `_validate_car_path` | `ValueError` | Use path under allowed root |
| Profile mismatch (legacy JSON vs DAG-JSON) | Different CIDs for “same” object | Silent divergence if unchecked | Document profile per artifact type; golden tests |
| Simulated backend CID (`Qm…` from accelerate/kit fallbacks) | Backend returned non-multiformats path | Proceeds for offline/CI | Treat as non-portable; do not write into protocol fields without validation |

**Feature degradation vs fail-closed trust:** missing CAR encode is a feature
gap. Missing multiformats for a required protocol field is a hard failure for
that feature—not permission to invent an id. Trust decisions (authz, proof)
never become allow-by-default because hashing is unavailable
([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).

## 10. Extension points

1. **New artifact type:** pick or define a named byte profile; document it next
   to the type; prefer `canonical_dag_json_bytes` + `cid_for_dag_json` for new
   protocol work.
2. **New codec:** extend store/get paths with an explicit codec argument;
   update `validate_cid` allowlists at contract boundaries.
3. **New interchange format:** implement via `IPLDStorage` + serialization
   helpers; keep path validation for filesystem sinks.
4. **Tests:** golden vectors for canonical bytes; round-trip store → get →
   equal CID; CAR export/import when `ipld` extra is present.
5. **Docs:** update this guide and [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)
   if identity rules change (ADR supersession, not quiet edits).

**Anti-patterns:**

- Hashing pretty-printed or unsorted JSON for protocol fields.
- Treating gateway URLs, pin lists, or local paths as content ids.
- Labeling mock/simulated digests as multiformats CIDs in receipts.
- Putting business identity logic only inside MCP tool wrappers.
- Collapsing receipt/authorization/proof into “we have a CID.”

## 11. Invariants

1. **Content identity is content-addressed** under a named canonical profile.
2. **Canonical encoding is part of the contract**; profile drift is identity drift.
3. **Identifiers ≠ locations.** A CID does not assert pin, reachability, or backend.
4. **Identifiers ≠ indexes.** Indexes reference content; they are not the content id.
5. **Identifiers ≠ receipts.** Logging a CID is not evidence a pipeline succeeded.
6. **Identifiers ≠ authorizations or proof.** Digesting inputs does not admit
   side effects or verify theorems.
7. **Validate before trust** for inbound CID strings on contract surfaces.
8. **No synthetic production CIDs** when multiformats is unavailable.
9. **Provenance references identity; it does not replace it.**
10. **CAR and local cache are transport/performance layers**, not alternate identity systems.

## 12. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Content identity | Identity = canonical bytes + CID profile | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Strict DAG-JSON for new work | Fail closed on non-JSON / non-finite | `cid_utils.canonical_dag_json_bytes` |
| IR without optional deps | IR identity must not depend on multiformats install | `ir-canonical-json-v1` |
| Lazy IPLD extras | Missing CAR/libipld degrades features, not identity rules | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| Local-only IPLD mode | Progress without daemon; integrity still hash-based when multiformats present | `IPLDStorage._store_local` |

Alternatives rejected (brief):

- Location-based identity — breaks multi-backend replication.
- UUID-only identity — no integrity across systems.
- Provenance graph as identity — lineage is not byte equality.
- Single raw-UTF-8 hash for all objects — loses structure and codec interop.

## 13. Security, privacy, and trust boundaries

- **Trust boundary:** untrusted CID strings and CAR files must be validated
  (decode + allowlist + recompute where integrity is claimed).
- **Path boundary:** CAR write/read confined by safe root.
- **Do not claim:** that a CID proves policy admission, legal correctness, or
  solver-checked theorems.
- **Privacy:** content-addressed systems leak equality (same CID ⇒ same bytes);
  do not place secrets in content-addressed public blocks without encryption
  owned by a higher layer.
- **Cache trust:** `IPLDStorage._block_cache` is process-local performance; do
  not treat cache hits as external attestation.

## 14. Observability and operations

- Warnings when falling back to local-only IPLD mode after router failures.
- `OptimizedEncoder` / `PerformanceStats` record encode/decode timings and
  codec cache hits/misses (performance, not trust).
- Operator recovery: reinstall `ipld` / `multiformats` extras; restart daemon;
  call `IPLDStorage.connect()`; re-import CAR; re-pin via backends guide.

## 15. Validation

Bounded, offline checks preferred:

```bash
# Guides present
test -s docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md
test -s docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md

# Required topic coverage
rg -n 'canonical|CID|CAR|cache|backend|integrity' \
  docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md \
  docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md

# Source helpers still present
rg -n 'canonical_dag_json_bytes|cid_for_dag_json|validate_cid|cid_for_bytes' \
  ipfs_datasets_py/utils/cid_utils.py
rg -n 'export_to_car|import_from_car|class IPLDStorage' \
  ipfs_datasets_py/processors/storage/ipld/storage.py
rg -n 'ir-canonical-json-v1|CANONICAL_JSON_PROFILE' \
  ipfs_datasets_py/logic/ir_core/canonical.py

# Optional: focused tests when extras installed
# pytest tests/ -q -k 'cid or car or ipld' --collect-only
```

**Limitations:** full CAR/IPFS integration tests need optional extras and often
a daemon; absence of extras is an availability issue, not a license to redefine
identity.

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Routers, pins, caches, offline recovery |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Binding identity decision |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional multiformats/IPLD lifecycle |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Import hermeticity and RouterDeps |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain flows that emit CIDs |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Storage domain placement |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Kinds of truth and authority order |

## 17. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide (`IPFSDOC-023`) |
