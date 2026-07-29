# Knowledge Graphs UCAN Contract (ADR)

**Program:** `KGP`  
**Task:** `KGP-021` — Define graph UCAN resources, abilities, and caveats  
**Status:** Accepted  
**Date:** 2026-07-29  
**Contract version:** `kg-ucan-contract/v1`  
**Depends on:** KGP-003 (service contract / GraphTarget)  
**Plan:** `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md`  
**Implementation:** `ipfs_datasets_py/knowledge_graphs/auth/contracts.py`  
**Token format:** MCP++ Profile C (`ipfs_datasets_py.mcp_server.ucan_delegation`) — **not** reinvented here

This ADR freezes the **graph-specific** UCAN vocabulary: resources, abilities,
caveats, containment, monotonic attenuation, and fail-closed issuance /
audience / expiry / revocation / replay / error / audit behavior. Enforcement
inside `GraphService` is KGP-022; adversarial matrices are KGP-023.

---

## 1. Decision summary

1. MCP++ (and optional Python/CLI policy contexts) authorize graph operations
   with UCAN-style capabilities over **`kg://` resources**.
2. The closed ability set is `graph/list`, `graph/read`, `graph/query`,
   `graph/write`, `graph/admin`, `graph/pin`, `graph/delegate`.
3. Caveats narrow authority along **branch, revision, query, property, row,
   byte, depth, time, audience, and count** dimensions.
4. Every delegation hop must **contain** resources, **attenuate** abilities,
   and **monotonically tighten** caveats and validity windows.
5. Validation is **fail-closed** before catalog lookup or shard fetch.
6. Allow and deny outcomes emit **redacted, content-addressed receipts**.
7. This module **adapts** existing Profile C tokens; it does not define a new
   JWT/CBOR token codec.

---

## 2. Resources

### 2.1 Canonical URI grammar

Same as `GraphTarget` in `knowledge_graphs_service_contract.md`:

```text
kg://<tenant>
kg://<tenant>/*
kg://<tenant>/<graph_id>
kg://<tenant>/<graph_id>/branches/<branch>
kg://<tenant>/<graph_id>/revisions/<revision>
```

| Form | Meaning |
| --- | --- |
| `kg://t` / `kg://t/*` | Tenant-wide authority (all graphs under `t`) |
| `kg://t/g` | All branches and revisions of graph `g` |
| `kg://t/g/branches/b` | Branch-pinned authority only |
| `kg://t/g/revisions/r` | Immutable revision-pinned authority only |

Rules:

- Scheme is always `kg://` (lowercase).
- `tenant`, `graph_id`, and `branch` use the service slug grammar.
- `revision` uses the CID / catalog id character class.
- Branch and revision **must not** both appear on one resource.

### 2.2 Resource containment

`resource_contains(parent, child)` is true when authority granted on *parent*
may be exercised (or further delegated) on *child*:

| Parent | Child | Contained? |
| --- | --- | --- |
| Equal URI | same | yes |
| `kg://t` or `kg://t/*` | any resource under tenant `t` | yes |
| `kg://t/g` | `kg://t/g`, branch, or revision of `g` | yes |
| `kg://t/g/branches/b` | only that exact branch URI | yes |
| `kg://t/g/revisions/r` | only that exact revision URI | yes |
| Different tenants | any | **no** |
| Narrow parent | broader child | **no** |

Cross-tenant resources never contain each other (confused-deputy guard).

---

## 3. Abilities

### 3.1 Closed set

| Ability | Typical operations |
| --- | --- |
| `graph/list` | list graphs / branches |
| `graph/read` | describe, open, read snapshot metadata |
| `graph/query` | Cypher / SPARQL / hybrid / traversal queries |
| `graph/write` | write, begin/commit/rollback transaction |
| `graph/admin` | create, delete, branch lifecycle |
| `graph/pin` | pin / unpin roots |
| `graph/delegate` | issue further attenuated delegations |

Operation → ability mapping lives in `OPERATION_ABILITIES` and mirrors the
service default authorizer vocabulary (`_OP_ABILITIES`) plus pin/delegate.

### 3.2 Ability attenuation lattice

A parent ability may be attenuated only to abilities in its downward set
(always including itself):

| Parent | May attenuate to |
| --- | --- |
| `graph/admin` | all graph abilities |
| `graph/write` | `write`, `read`, `query`, `list` |
| `graph/read` | `read`, `list` |
| `graph/query` | `query` |
| `graph/list` | `list` |
| `graph/pin` | `pin` |
| `graph/delegate` | `delegate` |

Attenuation is **monotonic**: a child link must never gain an ability outside
every covering parent capability’s downward set.

---

## 4. Caveats

### 4.1 Closed keys

| Key | Type | Semantics |
| --- | --- | --- |
| `branch` | set of branch slugs | allow-list of branches |
| `revision` | set of revision ids | allow-list of revisions |
| `query` | set of query kinds | `cypher`, `sparql`, `graphql`, `hybrid`, `traversal`, `vector`, `fulltext`, `describe`, `list` |
| `property` | set of property labels/keys | allow-list for projected or written properties |
| `row` | non-negative int | max rows returned / affected |
| `byte` | non-negative int | max response or write payload bytes |
| `depth` | non-negative int | max traversal depth |
| `time` | object | `expiry` / `not_before` / `max_ttl_seconds` (aliases: `exp`, `nbf`, `ttl`, …) |
| `audience` | set of principal DIDs | further restrict who may invoke |
| `count` | non-negative int | max mutations / uses under this grant |

Absence of a key means **unrestricted** on that dimension (service budgets may
still apply). Unknown keys are rejected (`unknown_caveat_key`).

### 4.2 Monotonic caveat attenuation

When the parent restricts a dimension, the child **must** preserve a
restriction that is no broader:

| Dimension | Child rule vs parent |
| --- | --- |
| set keys (`branch`, `revision`, `query`, `property`, `audience`) | child set ⊆ parent set; child set required if parent set present |
| upper bounds (`row`, `byte`, `depth`, `count`) | child ≤ parent; child bound required if parent bound present |
| `time.expiry` | child expiry ≤ parent expiry (earlier or equal) |
| `time.not_before` | child nbf ≥ parent nbf (later or equal) |
| `time.max_ttl_seconds` | child ≤ parent |

Unrestricted parent dimensions may be newly restricted by the child (narrowing
is always allowed).

### 4.3 Request admission

`caveats_allow_request` evaluates a concrete invocation (branch, revision,
query kind, properties, row/byte/depth/count, audience, clock) against a grant.
Failure reasons include `caveat_not_attenuated`, `audience_mismatch`,
`not_yet_valid`, and `expired`.

---

## 5. Delegation chain rules

A chain is an ordered list of links **root → … → leaf**. Each link carries
issuer, audience, capabilities, optional expiry / not_before / cid / proof_cid /
nonce, and optional link-level caveats.

### 5.1 Issuance (issuer / audience linkage)

- Link `0` is the root (issuer is the resource authority / policy root).
- For every `i ≥ 1`, `links[i].issuer == links[i-1].audience`.
- Breaks fail with `issuer_mismatch` → TypedError `FORBIDDEN`.

### 5.2 Per-hop attenuation

For every consecutive pair `(parent, child)`:

1. **Resource:** each child capability resource is contained in some parent
   capability resource.
2. **Ability:** each child ability is in the downward set of some covering
   parent ability.
3. **Caveats:** child link caveats attenuate parent link caveats; each child
   capability attenuates some parent capability’s caveats.
4. **Expiry window:** if parent has `expiry`, child must set `expiry ≤ parent`;
   child must not weaken `not_before`.

### 5.3 Audience

- When an invoker principal is required, it must equal the **leaf audience**.
- Link or capability `audience` caveats must include the invoker when present.
- Mismatch → `audience_mismatch` → `FORBIDDEN`.
- Missing invoker when required → `missing_principal` → `UNAUTHORIZED`.

### 5.4 Expiry / not-before

- Every link must be active at validation time (`not_before ≤ now ≤ expiry`
  when those fields are set).
- Failures: `not_yet_valid`, `expired` → `FORBIDDEN`.

### 5.5 Revocation

- A set of revoked CIDs is consulted for every link `cid` and `proof_cid`.
- Any hit → `revoked` → `FORBIDDEN`.
- Revocation checks run **before** capability exercise and before catalog /
  shard access (enforcement task).

### 5.6 Replay / nonce / idempotency

- Nonces observed in a replay cache cause `replay` → `FORBIDDEN`.
- Policies may `require_nonce` for invocations; mutating abilities
  (`write`, `admin`, `pin`, `delegate`) are the primary consumers of
  nonce / idempotency binding at the service boundary.
- This contract defines the validation hooks; the durable nonce store is an
  enforcement concern (KGP-022).

### 5.7 Leaf cover

After chain structural checks, the leaf must grant at least one capability that:

- contains the requested resource, and
- attenuates to the required ability, and
- admits the request under its caveats.

Otherwise → `capability_missing` → `FORBIDDEN`.

### 5.8 Empty / missing token

- Empty chain → `empty_chain` → `UNAUTHORIZED`.
- Missing principal when required → `UNAUTHORIZED`.

---

## 6. Error and audit behavior

### 6.1 TypedError mapping

| Deny reason | Service code |
| --- | --- |
| `missing_token`, `missing_principal`, `empty_chain` | `UNAUTHORIZED` |
| `invalid_*`, `unknown_*`, `nonce_required` | `INVALID_REQUEST` |
| containment / attenuation / audience / expiry / revoke / replay / capability | `FORBIDDEN` |

Full map: `ERROR_CODE_MAP` in `contracts.py`. Retryable flags follow the
service catalog (`UNAUTHORIZED` / `FORBIDDEN` are not retryable).

### 6.2 Fail-closed posture

Authorization decisions must complete **before**:

- catalog tenant/graph/branch lookup,
- revision manifest fetch,
- shard / CAR / Parquet payload access,
- query planning against graph data.

No “best effort allow” on partial chains, missing proofs, or clock skew
beyond explicit not-before/expiry rules.

### 6.3 Audit receipts

Every allow and deny emits a content-addressed receipt:

| Field | Purpose |
| --- | --- |
| `decision` | `allow` \| `deny` |
| `principal` | invoker / leaf audience |
| `resource` / `ability` | requested target |
| `reason` / `error_code` | deny taxonomy |
| `policy_digest` | hash of policy metadata |
| `request_digest` | hash of redacted request |
| `chain_digest` | hash of chain link descriptors |
| `receipt_cid` | `sha256:…` of the receipt payload |
| `contract_version` | `kg-ucan-contract/v1` |

**Redaction denylist** (keys and substrings): raw tokens, JWTs, signatures,
secrets, passwords, bearer headers, raw query text, property values, row
payloads. See `AUDIT_REDACT_KEYS` and `redact_for_audit`.

Receipts are safe to log and cross-surface; they never re-embed graph
contents or UCAN signatures.

---

## 7. Profile C adapter (no new token format)

| Contract type | Profile C source |
| --- | --- |
| `GraphCapability.resource` / `.ability` | `Capability.resource` / `.ability` |
| `GraphDelegationLink` | `Delegation` / `DelegationToken` via `link_from_delegation_token` |
| Graph caveats | carried as structured metadata alongside tokens until enforcement stores them in the invocation context (not a new JWT claim codec in this task) |
| Export | `link_to_profile_c_capability_dicts` → `[{resource, ability}, …]` |

Wallet UCAN grants (`ipfs_datasets_py.wallet.ucan`) may be adapted similarly
in later tasks; attenuation rules remain those defined here.

---

## 8. Relationship to later tasks

| Task | Consumes this ADR for |
| --- | --- |
| KGP-022 | Enforce chain validation inside `GraphService`; emit receipts |
| KGP-023 | Adversarial / negative matrices and MCP graph UCAN tests |
| KGP-G070 | Goal-level UCAN authorization and audit evidence |

---

## 9. Explicit non-goals (this ADR)

- Implementing `GraphAuthorizationService` enforcement (KGP-022)
- Cryptographic signature verification details (Profile C / DID key managers)
- Durable revocation lists or nonce stores
- Changing protected plan / objectives / todo files
- Inventing a parallel UCAN token wire format

---

## 10. Validation

```bash
python -m pytest -q tests/security/knowledge_graphs/test_ucan_contracts.py
```

Executable coverage includes resource containment, ability lattice, caveat
monotonicity, full-chain issuance/audience/expiry/revocation/replay checks,
error-code mapping, and audit redaction.
