# UI/UX IR — MCP-IDL Identity Interoperability Profile

| Field | Value |
| --- | --- |
| Interface | `MCPIDLIdentityInterop@1` |
| Program | `UIR` / board `ipfs-datasets-ui-ux-ir-v1` |
| Task | `UIR-002` |
| Status | Frozen for M0 / UIR-G010 |
| Date | 2026-08-01 |
| Parent contract | `external/ipfs_datasets/docs/architecture/UI_UX_IR_CONTRACT.md` |
| Machine-readable vectors | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/v1/mcp_idl_identity_vectors.json` |
| Contract tests | `external/ipfs_datasets/tests/unit/logic/ui_ux_ir/test_mcp_idl_identity_contract.py` |

This document freezes the **verified MCP interface identity** profile used by
UI/UX IR. It is an interoperability and evidence contract only: it does **not**
rewrite existing MCP registries, normalize legacy identifiers in place, or
mutate production descriptor stores.

## 1. Purpose and non-claims

UI/UX IR declarations may *reference* MCP-IDL interfaces. Those references must
use a single, preimage-verified identity domain for the interface itself, and
must never be confused with:

- the UIIR declaration identity (`ui_ir_cid`);
- typed historical aliases (`legacy_alias`);
- projection, proof, observation, mediation, or runtime receipt identities.

### 1.1 Explicit rejections

| Rejected claim | Rationale |
| --- | --- |
| `ui_ir_cid == interface_cid` | Different domains and preimages; comparing them as interchangeable is an authority error. |
| `interface_cid == legacy_alias` | Historical `sha256:*`, mock `bafy-*`, placeholder `cidv1-sha256-*`, and mislabeled labels are typed aliases only. |
| Mutable-cache identity as authority | Caching an interface CID on a mutable descriptor object without invalidation is non-authoritative. |
| Mislabeled DAG-PB as interface authority | Encoding raw descriptor bytes under multicodec `dag-pb` (`0x70`) is incompatible with the reviewed profile. |
| Silent fixture rewrite | Incompatible existing fixtures are inventoried with disposition; they are not rewritten in place by this task. |
| UIIR owns MCP operation contracts | MCP-IDL remains the operation/schema authority; UIIR only binds stable references. |

## 2. Authority

### 2.1 Interface identity authority

| Role | Path / symbol |
| --- | --- |
| Package authority surface | `external/ipfs_accelerate/ipfs_accelerate_py/mcp_server/mcplusplus/idl_registry.py` |
| Reviewed CIDv1 byte constructor | `external/ipfs_accelerate/ipfs_accelerate_py/mcp_server/mcplusplus/kubo_cid.cid_for_bytes` |
| Descriptor canonicalization (JSON) | `idl_registry.canonicalize_descriptor` — deterministic `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)` UTF-8 |
| Cross-check (optional) | `multiformats.CID` / `multihash` with CIDv1, codec `raw`, multihash `sha2-256`, multibase `base32` |

**Interface authority rule:** a verified `interface_cid` is the CIDv1 / raw /
sha2-256 / base32 of the **canonical descriptor preimage bytes**. Callers that
need verified interface identity must compute or verify against that profile.
They must not treat the current migration placeholder returned by
`idl_registry.compute_interface_cid` (`cidv1-sha256-<hex>`) as a verified
CIDv1 string (see §7).

### 2.2 Related non-authorities (read-only inventory)

| Surface | Current identity form | Disposition for UIIR |
| --- | --- | --- |
| `idl_registry.compute_interface_cid` | `cidv1-sha256-<hex digest>` placeholder | Incompatible placeholder; typed `legacy_alias` / migration-only until a later adapter lands |
| `swissknife/src/services/mcp/mcp-idl.ts` `computeInterfaceCID` | `sha256:<hex>` | Typed `legacy_alias` |
| `ipfs_datasets_py.mcp_server.interface_descriptor.compute_cid` | CIDv1 **dag-pb** / sha2-256 / base32 (`bafybei…`) | **Rejected** as interface authority (mislabeled codec) |
| Mock / fixture IDs (`bafy-mock-…`, weak pseudo-CIDs) | Non-preimage labels | Typed `legacy_alias` only |

UIR-002 records these; UIR-030 (MCP-IDL source adapter) will inject/lazy-load
the verified authority without rewriting registries in place.

## 3. Frozen multiformats profile

| Parameter | Value |
| --- | --- |
| Profile name | `mcp-idl-interface-identity-v1` |
| CID version | `1` |
| Multicodec name | `raw` |
| Multicodec code | `0x55` |
| Multihash name | `sha2-256` |
| Multihash code | `0x12` |
| Digest size | `32` bytes |
| Multibase name | `base32` (RFC 4648 lowercase, no padding) |
| Multibase prefix | `b` |
| Wire shape | `b` + base32(`0x01 ‖ 0x55 ‖ 0x12 ‖ 0x20 ‖ sha256(preimage)`) |
| Typical prefix | `bafkrei…` (not `bafybei…`) |

### 3.1 Preimage construction

1. Build the **identity-bound descriptor object** (§4).
2. Canonicalize with sorted keys, compact separators, `ensure_ascii=True`, UTF-8:
   `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")`.
3. Hash with SHA-256 over those exact bytes.
4. Wrap as CIDv1 / raw / sha2-256 / base32 (`kubo_cid.cid_for_bytes` or equivalent).

Key order in the in-memory object **must not** affect identity (sort_keys).
Array order inside declared ordered collections **does** affect identity.

### 3.2 Preimage verification

Given candidate `interface_cid` and descriptor `D`:

1. Reject if `interface_cid` is not a lowercase CIDv1 string under the profile
   (wrong version, codec, multihash, base, length, or casing).
2. Recompute `expected = profile_cid(canonicalize(identity_bound(D)))`.
3. Accept only when `interface_cid == expected` (exact string equality).
4. Reject mismatched preimages, truncated digests, and double-hashed inputs.

## 4. Identity-affecting descriptor fields

All of the following fields are **bound in the preimage** when present on a
descriptor that claims verified `interface_cid` status. Omitting a field from
the preimage while advertising it on the wire is an identity error.

| Field | Required for verified profile | Notes |
| --- | --- | --- |
| `name` | yes | Interface logical name |
| `namespace` | yes | Owning namespace |
| `version` | yes | Interface version string |
| `methods` | yes | Ordered list of method records (see §4.1) |
| `errors` | yes | Interface-level error definitions (list; may be empty) |
| `requires` | yes | Capability requirement strings (list; may be empty) |
| `compatibility` | yes | Object with `compatible_with` / `supersedes` lists |
| `semantic_tags` | yes when claimed | Tag list; empty list is bound |
| `observability` | yes when claimed | e.g. `trace`, `provenance` |
| `interaction_patterns` | yes when claimed | e.g. `request_response`, `event_streams` |
| `resource_cost_hints` | yes when claimed | Cost/latency hints **are identity-affecting** under this profile |

### 4.1 Method record fields (identity-affecting)

When a method is included, the following keys are identity-affecting if present:

- `name`
- `input_schema` / `output_schema` (inline schemas)
- `input_schema_cid` / `output_schema_cid` (CID references; not dereferenced for identity)
- `errors` / `error_schema_cids`
- `event_schema` / `event_schema_cid`
- `streaming`
- `description` (if included in the bound object)

Adapters **must** pick a single snake_case or camelCase form for the bound
preimage; dual aliases on the wire must be normalized before hashing. This
profile's golden vectors use the snake_case form matching the accelerator
`build_descriptor` / registry corpus.

### 4.2 Non-identity fields

| Field / artifact | Effect on `interface_cid` |
| --- | --- |
| `interface_cid` itself | Must **not** appear inside the preimage |
| Registry insert timestamps, peer addresses, cache metadata | Excluded |
| Runtime compatibility verdicts | Excluded |
| UIIR documents, projections, proofs, observations, receipts | Separate domains |

## 5. Typed identity domains (never equated)

| Name | Domain | Verified form |
| --- | --- | --- |
| `interface_cid` | MCP interface descriptor preimage | CIDv1 / raw / sha2-256 / base32 (`bafkrei…`) |
| `ui_ir_cid` | UI/UX IR declaration preimage | Independent IR identity (see `ir_core` / UIR-011); never derived by copying `interface_cid` |
| `legacy_alias` | Historical or non-profile ID | Typed string with explicit disposition; never compared with `==` to a verified CID for authority |

**Hard rules:**

1. Never compare `ui_ir_cid` and `interface_cid` for equality as an authority check.
2. Never promote a `legacy_alias` to `interface_cid` without a fresh preimage
   verification under this profile.
3. A document may *record* both a verified `interface_cid` and one or more
   `legacy_alias` values as parallel metadata; recording is not equivalence.

## 6. Rejected behaviors

### 6.1 Stale mutable-cache identity

Any implementation that stores `_interface_cid` (or equivalent) on a **mutable**
descriptor instance and returns the cached value after field mutation without
recomputing from the current preimage is **non-authoritative**.

Observed example (read-only inventory):
`ipfs_datasets_py.mcp_server.interface_descriptor.InterfaceDescriptor.interface_cid`
caches on first access; mutating `name` afterward leaves a stale CID.

UIIR and adapters must recompute from immutable snapshot bytes or freeze the
descriptor before hashing.

### 6.2 Mislabeled DAG-PB

Encoding the same raw JSON preimage with multicodec `dag-pb` (`0x70`) yields a
different CID string (typically `bafybei…`) that is **not** a verified
`interface_cid` under this profile, even when the multihash digest matches.

### 6.3 Pseudo-CIDs and placeholders

The following are never accepted as verified `interface_cid`:

- `cidv1-sha256-<hex>` (accelerator migration placeholder);
- `sha256:<hex>` (SwissKnife Profile A string form);
- `bafy-mock-…` and other mock labels;
- truncated, upper-case, or wrong-codec CIDv1 strings;
- digests of non-canonical JSON (unsorted keys, non-compact separators, ASCII-escaping drift).

### 6.4 Partial field binding

Excluding identity-affecting fields such as `resource_cost_hints` from the
preimage while still serializing them on the descriptor is rejected for
verified interface identity. (The datasets `InterfaceDescriptor.canonical_bytes`
path currently exhibits this exclusion; recorded in §7.)

## 7. Incompatible existing fixtures and surfaces (inventory)

This section **records** incompatibilities. It does not rewrite them.

| ID | Location | Observed form | Issue | Disposition |
| --- | --- | --- | --- | --- |
| `inv.accelerator_placeholder` | `idl_registry.compute_interface_cid` | `cidv1-sha256-<hex>` | Not a real CIDv1 multiformats string | `legacy_alias` / migration placeholder; digest may match profile SHA-256 body |
| `inv.ts_sha256_prefix` | `swissknife/.../mcp-idl.ts` `computeInterfaceCID` | `sha256:<hex>` | Non-CID wire form | `legacy_alias` |
| `inv.datasets_dagpb` | `ipfs_datasets_py.mcp_server.interface_descriptor.compute_cid` | CIDv1 **dag-pb** | Mislabeled codec vs raw | Reject for interface authority |
| `inv.datasets_mutable_cache` | `InterfaceDescriptor._interface_cid` | Stale cache after mutation | Mutable-cache identity | Reject as authority |
| `inv.datasets_hints_excluded` | `InterfaceDescriptor.canonical_bytes` | Omits `resource_cost_hints` | Incomplete identity binding | Incompatible with §4 |
| `inv.mock_bafy` | Various fixtures | `bafy-mock-…` / weak pseudo-CIDs | No preimage | `legacy_alias` only |

Golden vectors for these incompatibilities live in
`mcp_idl_identity_vectors.json` under `incompatible_inventory` and
`rejection_cases`.

## 8. Cross-language and golden vector requirements

The fixture file publishes:

1. **Profile constants** — codes, names, and constructor reference.
2. **Golden descriptor** — full identity-bound object, UTF-8 preimage, SHA-256
   digest, verified `interface_cid`.
3. **Field-sensitivity cases** — one mutation per identity-affecting field
   proving the CID changes.
4. **Rejection cases** — pseudo-CIDs, DAG-PB twin, mismatched preimage, domain
   conflation attempts.
5. **Domain separation sample** — a distinct `ui_ir_cid` for a toy UIIR
   preimage that must not equal the golden `interface_cid`.
6. **Incompatible inventory** — frozen records of existing non-authoritative
   surfaces (no silent rewrite).

Python contract tests recompute the golden CID via
`kubo_cid.cid_for_bytes` and, when available, cross-check with `multiformats`.

## 9. Adapter obligations (forward reference)

Later work (`UIR-030` and the TypeScript codec) must:

1. Inject or lazy-load this profile as the verified interface authority;
2. Preserve typed `legacy_alias` values without equating them to `interface_cid`;
3. Verify preimages before accepting remote or imported interface CIDs;
4. Emit adapter loss when UI semantics cannot be derived from IDL;
5. Never treat interface identity as an execution grant.

## 10. Relationship to UIIR declaration identity

| Concern | Owner |
| --- | --- |
| Verified MCP `interface_cid` | This profile (`MCPIDLIdentityInterop@1`) |
| UIIR `ui_ir_cid` | UI/UX IR schema + `ir_core` identity (UIR-010 / UIR-011) |
| Program / Intent identities | Intent IR / Invocation IR |
| Runtime receipts | ORB / mediation layers |

A UIIR document may embed an `interface_cid` **reference**. That reference is
metadata about an external MCP interface; changing projections or proofs of the
UIIR document must not rewrite the referenced interface preimage, and changing
the interface descriptor must not silently rewrite `ui_ir_cid`.

## 11. Conformance checklist

An implementation conforms to `MCPIDLIdentityInterop@1` when it:

- [ ] Uses CIDv1 / raw (`0x55`) / sha2-256 / base32 for verified `interface_cid`;
- [ ] Canonicalizes descriptor preimages with sorted-key compact JSON UTF-8;
- [ ] Binds every identity-affecting field listed in §4;
- [ ] Verifies preimages before accepting interface CIDs as verified;
- [ ] Rejects DAG-PB, placeholders, pseudo-CIDs, and stale mutable caches;
- [ ] Never equates `ui_ir_cid`, `interface_cid`, and `legacy_alias`;
- [ ] Records incompatible legacy surfaces instead of silently rewriting them;
- [ ] Passes `tests/unit/logic/ui_ux_ir/test_mcp_idl_identity_contract.py`.
