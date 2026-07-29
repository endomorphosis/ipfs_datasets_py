# Knowledge Graphs Service Contract (ADR)

**Program:** `KGP`  
**Task:** `KGP-003` — Ratify the canonical API, identity, and compatibility ADR  
**Status:** Accepted  
**Date:** 2026-07-29  
**Contract version:** `kg-service-contract/v1`  
**Depends on:** KGP-001 (lifecycle contract matrix), KGP-002 (inventory)  
**Plan:** `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md`  
**Companion:** `docs/architecture/knowledge_graphs_compatibility.md`

This ADR ratifies the **canonical control-plane contract** for production
knowledge graphs. It is the normative specification for identity, lifecycle
requests/results, typed errors, the JSON-safe query envelope, and the
**one-service rule**. Implementation lands in later tasks (catalog, manifest,
`GraphService`); this document freezes the shapes those tasks must obey.

---

## 1. Decision summary

1. Every public graph operation resolves an explicit **`GraphTarget`**. No
   ambient process state, default empty graph, or freshly constructed manager
   may stand in for a target.
2. All Python, CLI, MCP, and MCP++ entry points call one long-lived
   **`GraphService`** (the **one-service rule**).
3. Successful and failed outcomes use versioned, **JSON-safe** result envelopes
   and a closed set of **typed error codes**.
4. Compatibility with legacy graph classes is governed by
   `knowledge_graphs_compatibility.md` (adopt / adapt / deprecate tiers).

---

## 2. The one-service rule

| Rule ID | Normative statement |
| --- | --- |
| `OSR-1` | There is exactly one orchestration type for production graph lifecycle: `GraphService`. |
| `OSR-2` | Python API, CLI, MCP tools, and MCP++ dispatch are **thin surfaces** over a shared service instance (or a client bound to the same catalog + storage configuration). |
| `OSR-3` | Surfaces **must not** construct an ambient empty graph, invent a process-local graph identity, or instantiate a fresh manager per call when durability or multi-call transactions are required. |
| `OSR-4` | Authorization (including UCAN for MCP++) is enforced **inside** `GraphService` before catalog lookup or shard fetch, so policy is not transport-only. |
| `OSR-5` | Query and write implementations are **delegates** of the service (adapters). Callers never select a raw `GraphEngine` or storage backend as the public catalog. |
| `OSR-6` | A new client/process that names a committed `GraphTarget` can **reopen** that graph after restart; success never depends on in-process caches alone. |

**Non-goals of this rule:** extraction helpers, offline migration tools, and
read-only corpus adapters may exist outside `GraphService`, but they **publish
or consume** through the service (or adapters that produce revision manifests)
before their outputs are treated as production graphs.

---

## 3. GraphTarget

### 3.1 Purpose

`GraphTarget` is the sole public address for a graph snapshot or branch head.
Every create/list/describe/open/branch/delete/write/query/transaction request
carries a target (create may omit revision and supply only tenant + graph id +
branch defaults).

### 3.2 Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant` | string | yes | Tenant slug. Non-empty; lowercase ASCII letters, digits, `_`, `-`; length 1–64. |
| `graph_id` | string | yes | Graph id within the tenant. Same character class and length as `tenant`. |
| `branch` | string \| null | conditional | Mutable branch name (default `main` when selecting a head). Mutually exclusive with a pin to an immutable revision when `revision` is set for **read** snapshots; writers always name a branch. |
| `revision` | string \| null | conditional | Immutable revision identifier (content-addressed CID or catalog revision id). When set for reads, the service opens that snapshot and ignores ambient branch movement. |
| `storage_profile` | string \| null | no | One of: `parquet`, `ipfs_ipld`, `ipfs_kit`, `hybrid`. Null means catalog default for the graph. |
| `uri` | string | derived | Canonical URI form (see §3.3). |

### 3.3 Canonical URI

```text
kg://<tenant>/<graph_id>
kg://<tenant>/<graph_id>/branches/<branch>
kg://<tenant>/<graph_id>/revisions/<revision>
```

Rules:

- Scheme is always `kg://` (lowercase).
- Path segments are percent-encoded only when required by URI rules; ids that
  match the slug character class are written literally.
- Branch and revision **must not** both appear in the same URI.
- `GraphTarget.from_uri` / `to_uri` are inverses for valid targets.
- MCP++ UCAN resources use this same URI form (plan § MCP++ and UCAN).

### 3.4 Validation (normative)

A target is **invalid** when any of the following hold:

| Code | Condition |
| --- | --- |
| `TARGET_EMPTY_TENANT` | `tenant` missing or empty after strip |
| `TARGET_EMPTY_GRAPH` | `graph_id` missing or empty after strip |
| `TARGET_BAD_SLUG` | `tenant`, `graph_id`, or `branch` fails slug pattern `^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$` (single-char slugs allowed as `[a-z0-9]`) |
| `TARGET_BRANCH_AND_REVISION` | both `branch` and `revision` set on a URI or request that forbids dual selection |
| `TARGET_AMBIGUOUS` | neither branch nor revision where an operation requires one |
| `TARGET_BAD_URI` | URI does not match the `kg://` grammar |
| `TARGET_BAD_PROFILE` | `storage_profile` not in the closed set and not null |

Slug pattern intent: DNS-ish identifiers, no path separators, no uppercase, no
spaces. Revisions (CIDs) are **not** slugs; they use the CID / catalog id
character class (`[a-zA-Z0-9._:-]+`, length 1–128).

### 3.5 JSON shape

```json
{
  "tenant": "acme",
  "graph_id": "skills",
  "branch": "main",
  "revision": null,
  "storage_profile": "hybrid",
  "uri": "kg://acme/skills/branches/main"
}
```

---

## 4. Lifecycle request and result

### 4.1 Operations

| Operation | Purpose | Target requirements |
| --- | --- | --- |
| `create` | Register graph identity, default branch, storage profile | tenant + graph_id; branch defaults to `main`; no revision |
| `list` | List graphs for a tenant (optional filters) | tenant; graph_id optional as filter |
| `describe` | Return catalog metadata + head | tenant + graph_id; optional branch |
| `open` | Resolve target to a revision snapshot handle | tenant + graph_id + (branch **or** revision) |
| `branch` | Create or update a named branch pointer | tenant + graph_id + branch; may set from revision |
| `delete` | Tombstone graph or branch | tenant + graph_id; optional branch |
| `write` | Stage and commit mutations under a branch | tenant + graph_id + branch |
| `query` | Run a bounded query against a snapshot | tenant + graph_id + (branch **or** revision) |
| `begin_tx` / `commit_tx` / `rollback_tx` | Explicit transaction boundaries | same as write; requires idempotency key for commit |

### 4.2 LifecycleRequest

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `contract_version` | string | yes | Must be `kg-service-contract/v1` for this ADR |
| `operation` | string | yes | One of the operations in §4.1 |
| `target` | GraphTarget object | yes | See §3 (list may use tenant-only partial target) |
| `idempotency_key` | string \| null | conditional | Required for create/write/commit retries; 1–128 chars |
| `params` | object | no | Operation-specific parameters (entity payloads, query text, options) |
| `budgets` | object \| null | no | Optional `time_ms`, `max_rows`, `max_bytes`, `max_depth`, `max_fanout`, `max_memory_bytes` |
| `auth` | object \| null | no | Capability token reference / principal (surface-specific) |
| `request_id` | string \| null | no | Correlation id for audit and MCP++ |

### 4.3 LifecycleResult

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `contract_version` | string | yes | `kg-service-contract/v1` |
| `status` | string | yes | `success` \| `error` |
| `operation` | string | yes | Echo of request operation |
| `target` | GraphTarget object \| null | yes on success for graph ops | Resolved target (with revision filled after open/write) |
| `result` | object \| null | conditional | Operation payload (see §4.4); null on pure errors |
| `error` | TypedError object \| null | conditional | Present iff `status=error` |
| `warnings` | array of strings | no | Non-fatal notices |
| `request_id` | string \| null | no | Echo / assigned correlation id |
| `authorization_receipt_ref` | string \| null | no | Content-addressed allow/deny receipt reference |

### 4.4 Success payload conventions

| Operation | `result` keys (minimum) |
| --- | --- |
| `create` | `graph_id`, `uri`, `branch`, `revision` (initial empty or bootstrap revision), `storage_profile` |
| `list` | `graphs` (array of describe summaries) |
| `describe` | `uri`, `branches`, `head_revision`, `storage_profile`, `graph_kind`, `created_at`, `updated_at` |
| `open` | `uri`, `revision`, `branch` (if resolved from head), `snapshot_id` |
| `branch` | `branch`, `revision` |
| `delete` | `tombstone` (bool), `uri` |
| `write` | `revision` (new head), `parent_revision`, `mutation_count` |
| `query` | **Query result envelope** (§5) nested as `result.query` **or** the envelope is the entire `result` when `operation=query` |
| transactions | `transaction_id`, `state` (`open` \| `prepared` \| `committed` \| `rolled_back`) |

---

## 5. JSON-safe query envelope

### 5.1 Why

KGP-001 observed that `query_cypher` returns `neo4j_compat.result.Result`
objects that are **not** JSON serializable. Production surfaces require a
versioned, pure-JSON envelope so CLI `--json`, MCP, and MCP++ never depend on
pickle, custom encoders, or pretty-print side channels.

### 5.2 QueryResultEnvelope fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `envelope_version` | string | yes | `kg-query-envelope/v1` |
| `schema` | string | yes | Result schema id (e.g. `cypher-table/v1`, `node-scan/v1`) |
| `target` | GraphTarget JSON | yes | Snapshot that was queried (revision must be resolved) |
| `revision` | string | yes | Immutable revision id/CID for the snapshot |
| `columns` | array of strings | yes | Column names; empty array when rows are objects with stable keys |
| `rows` | array | yes | JSON values only (see §5.3); each row is an array (aligned with columns) **or** an object |
| `row_count` | integer | yes | `len(rows)` for this page |
| `cursor` | string \| null | no | Opaque, **revision-bound** continuation token; null when exhausted |
| `statistics` | object | yes | At least `elapsed_ms` (number); may include `nodes_visited`, `edges_visited`, `bytes_read`, `shards_touched` |
| `warnings` | array of strings | yes | May be empty |
| `provenance` | object \| null | no | Producer, corpus, or query plan digests |
| `authorization_receipt_ref` | string \| null | no | Audit receipt reference |
| `truncated` | bool | yes | True if budgets cut the result short |
| `query` | object | yes | Echo: `{ "language": "cypher"\|"scan"\|…, "text": "…", "params": {…} }` |

### 5.3 JSON-safe value domain

Allowed leaf values in `rows`, `params`, and `statistics`:

- `null`, `bool`, `int`, `float` (finite only; reject `NaN` / `±Infinity`)
- `str`
- `list` / `dict` composed only of allowed values
- Integers that exceed JSON number safety for JS consumers **should** be
  emitted as strings with an adjacent type hint only when a column schema
  declares `type=integer_string`; default is IEEE-safe integers

**Forbidden** in the envelope:

- Python `bytes`, `datetime`, custom classes, graph `Node`/`Relationship`/`Result`
- Sets, tuples (encode as lists)
- Non-string dict keys

`json.dumps(envelope, allow_nan=False)` **must** succeed for every successful
query result.

### 5.4 Example

```json
{
  "envelope_version": "kg-query-envelope/v1",
  "schema": "cypher-table/v1",
  "target": {
    "tenant": "acme",
    "graph_id": "skills",
    "branch": null,
    "revision": "bafyreib2…",
    "storage_profile": "hybrid",
    "uri": "kg://acme/skills/revisions/bafyreib2…"
  },
  "revision": "bafyreib2…",
  "columns": ["name", "score"],
  "rows": [["alice", 0.91], ["bob", 0.77]],
  "row_count": 2,
  "cursor": null,
  "statistics": {"elapsed_ms": 12.5, "nodes_visited": 40},
  "warnings": [],
  "provenance": null,
  "authorization_receipt_ref": null,
  "truncated": false,
  "query": {
    "language": "cypher",
    "text": "MATCH (n:Person) RETURN n.name AS name, n.score AS score LIMIT 2",
    "params": {}
  }
}
```

---

## 6. Typed errors

### 6.1 TypedError object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | yes | Closed vocabulary in §6.2 |
| `message` | string | yes | Human-readable; no secrets |
| `retryable` | bool | yes | Whether a identical retry may succeed without client change |
| `details` | object | yes | JSON-safe context (ids, limits); may be empty |
| `cause_code` | string \| null | no | Nested/mapped storage or auth code |

Surfaces map TypedError to:

- Python: exception subclasses under a future
  `ipfs_datasets_py.knowledge_graphs.contracts.errors` (and/or bridge to
  existing `KnowledgeGraphError` hierarchy without leaking non-JSON details)
- CLI: non-zero exit for hard failures; `--json` prints the LifecycleResult
- MCP / MCP++: `status=error` tool payload with the same TypedError object

### 6.2 Error code catalog (v1)

| Code | HTTP-ish | retryable | When |
| --- | --- | --- | --- |
| `INVALID_REQUEST` | 400 | false | Malformed request / bad contract version |
| `INVALID_TARGET` | 400 | false | GraphTarget validation failure |
| `NOT_FOUND` | 404 | false | Unknown tenant/graph/branch/revision |
| `ALREADY_EXISTS` | 409 | false | Create on existing graph id |
| `CONFLICT` | 409 | true | CAS head conflict; client should re-read and retry with new base |
| `FENCED` | 409 | false | Writer lease epoch is stale |
| `UNAUTHORIZED` | 401 | false | Missing principal |
| `FORBIDDEN` | 403 | false | Capability/caveat denial |
| `BUDGET_EXCEEDED` | 429 | true | Time/row/byte/depth/fan-out/memory budget |
| `QUERY_PARSE` | 400 | false | Query language syntax error |
| `QUERY_EXECUTION` | 500 | false | Deterministic execution failure |
| `STORAGE` | 503 | true | Backend unavailable / transient IO |
| `INTEGRITY` | 500 | false | Checksum/CID mismatch, corrupt shard |
| `NOT_IMPLEMENTED` | 501 | false | Operation not yet available on this profile |
| `INTERNAL` | 500 | false | Unexpected failure (redacted message) |

Legacy exception types (`QueryError`, `StorageError`, `TransactionConflictError`,
…) **must** map into this catalog at the service boundary; they must not escape
public surfaces as opaque strings without a `code`.

---

## 7. Budgets and cursors

| Budget | Default posture |
| --- | --- |
| `time_ms` | Hard timeout; `BUDGET_EXCEEDED` or truncated page with `truncated=true` per operation policy |
| `max_rows` | Caps `rows` length per response page |
| `max_bytes` | Caps serialized payload size |
| `max_depth` | Caps path traversal depth |
| `max_fanout` | Caps adjacency expansion per hop |
| `max_memory_bytes` | Service-side working set guard |

Cursors are opaque strings, bound to `(graph_id, revision, query digest)`.
Reusing a cursor against a different revision returns `INVALID_REQUEST`.

---

## 8. Surface binding (normative intent)

| Surface | Binding |
| --- | --- |
| Python | `Client` / `AsyncClient` configured with catalog location; methods accept `GraphTarget` or URI strings |
| CLI | `ipfs_datasets_cli.py graph … --target kg://…` (or `--tenant` / `--graph` / `--branch`) |
| MCP | graph tools resolve a shared service; parameters include target fields |
| MCP++ | same tools + UCAN resource `kg://…` and abilities `graph/list`, `graph/read`, `graph/query`, `graph/write`, `graph/admin`, `graph/pin`, `graph/delegate` |

Cross-surface **golden vectors** (later conformance tasks) require byte-equal
JSON for `LifecycleResult` and `QueryResultEnvelope` after canonical key sort,
and equal TypedError `code` values.

---

## 9. Storage profiles (service view)

| Profile | Payload authority | Notes |
| --- | --- | --- |
| `parquet` | Versioned Parquet datasets under revision directories | Atomic publish; catalog holds heads only |
| `ipfs_ipld` | DAG-CBOR manifests + CAR objects | Verify CID after every fetch |
| `ipfs_kit` | Same semantics via `ipfs_kit_py` capability negotiation | No import-time silent fallback |
| `hybrid` | Parquet/CAR + verified local cache; remote root CID | Catalog records authoritative copy |

---

## 10. Relationship to later tasks

| Task | Consumes this ADR for |
| --- | --- |
| KGP-004 | Manifest fields aligned with target + storage profile |
| KGP-005 | Catalog keys = tenant/graph/branch/revision |
| KGP-006 | `GraphService` method signatures and envelopes |
| KGP-007+ | Transaction error codes `CONFLICT` / `FENCED` |
| KGP-016+ | Surface clients and deprecation of `KnowledgeGraphManager` |

---

## 11. Explicit non-goals (this ADR)

- Implementing `GraphService`, catalog SQLite, or storage adapters
- Migrating any corpus producer (see inventory; stage 6 gate)
- Changing protected plan/objectives/todo files
- Rewriting legacy `GraphEngine` / extraction APIs in place

---

## 12. Validation

Executable regression coverage for this contract:

```bash
python -m pytest -q \
  tests/unit/knowledge_graphs/contracts/test_graph_target.py \
  tests/unit/knowledge_graphs/contracts/test_result_envelope.py
```

Compatibility tiers and legacy class mapping:
`docs/architecture/knowledge_graphs_compatibility.md`.
