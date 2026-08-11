# ADR-001: Content Identity and Provenance

| Field | Value |
| --- | --- |
| Interface | `ContentIdentityDecision@1` |
| Task | `IPFSDOC-013` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture |
| Consulted | documentation-governance; data-platform; logic/IR maintainers |
| Source of truth | `ipfs_datasets_py/utils/cid_utils.py`; `ipfs_datasets_py/logic/ipld_cid.py`; `ipfs_datasets_py/logic/ir_core/canonical.py`; `ipfs_datasets_py/analytics/data_provenance.py`; `ipfs_datasets_py/analytics/data_provenance_enhanced.py`; `ipfs_datasets_py/ipfs_backend_router.py`; `benchmarks/logic_pipeline/content_addressing.py`; packaging extras for multiformats / IPLD |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Cross-cutting product decision distilled from current content-addressing, IR canonicalization, provenance, and storage backend contracts (`IPFSDOC-G032`) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

IPFS Datasets Python is an IPFS-native data and AI platform. Artifacts—dataset
bytes, processor outputs, IR documents, policy packets, benchmark receipts, and
lineage records—cross module, process, and network boundaries. Without a shared
identity model:

1. **Ambiguous equality.** Two JSON encodings of the same logical object can
   hash differently (key order, whitespace, non-finite numbers, `repr` fallbacks).
2. **Location coupling.** Callers treat HTTP URLs, filesystem paths, IPNS names,
   or pin set membership as durable identity; those resolve to *where* something
   was last seen, not *what* it is.
3. **Authority confusion.** A content identifier (CID), a storage pin, a
   provenance row, a policy receipt, and a proof attestation look similar in
   logs and docs but answer different questions.
4. **Lineage without integrity.** Transformation history that is not bound to
   content digests cannot detect silent mutation or reconstruct inputs for audit.
5. **Heterogeneous surfaces.** Library APIs, MCP tools, CLI, and benchmark
   protocols each need the same identity rules so agents and operators do not
   invent parallel “hash fields.”

Current tree evidence already implements pieces of the answer:

- **Canonical bytes and CIDs:** `utils.cid_utils` provides deterministic JSON
  serialization (`canonical_json_bytes`), a stricter fail-closed DAG-JSON path
  (`canonical_dag_json_bytes`—rejects NaN/infinity and non-JSON types), and CID
  construction (`cid_for_bytes`, `cid_for_obj`, `cid_for_dag_json`,
  `validate_cid`) using multiformats CIDv1, typically `sha2-256`, with codecs
  `raw` (exact bytes) and `dag-json` (structured objects).
- **Policy / Profile D artifacts:** `logic.ipld_cid` documents CIDv1 +
  `dag-json` + `sha2-256` so Helia and Kubo can store the same canonical block.
- **IR-family canonical profile:** `logic.ir_core.canonical` defines
  `ir-canonical-json-v1` (NFC text, sorted keys, finite decimals, set/multiset
  rules) without optional dependencies—so identity for IR contracts does not
  depend on heavy stacks.
- **Benchmark isolation:** `benchmarks/logic_pipeline/content_addressing.py`
  mirrors the package DAG-JSON byte contract without importing package root
  (avoids installer bootstrap side effects) while preserving the same multiformats
  standard.
- **Provenance:** `analytics.data_provenance` / `data_provenance_enhanced` and
  audit integrations record source → transform → merge lineage; enhanced paths
  may store provenance via IPLD and optionally cryptographically verify records.
  MCP `provenance_tools` expose recording over that domain logic.
- **Retrieval backends:** `ipfs_backend_router` addresses content by CID
  (`cat`, `pin`, `block_get`, …) across kit, accelerate, HTTP API, and Kubo CLI
  backends—CID is the key; backend choice is transport.

Forces that make a decision necessary: multi-backend IPFS access, optional
`multiformats`/IPLD extras, agent-facing tools that must not invent identities,
security and legal IR pipelines that bind digests into receipts, and the program
authority order that ranks tests/schemas and implementation above narrative
([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## Decision

We will treat **content identity** as a function of **canonical bytes** under a
declared encoding profile, and **CIDs** as the primary portable identifiers for
those bytes (or IPLD blocks). We will treat **provenance** as a separate
lineage graph that *references* content identities and operations, not as a
substitute for cryptographic content addressing.

### Decision details

1. **Canonical bytes first.** Equality and hashing are defined only after a
   documented byte encoding. Preferred profiles in this product:
   - **Exact bytes** → hash with codec `raw`.
   - **Structured protocol / receipt objects (new work)** →
     `canonical_dag_json_bytes` / `cid_for_dag_json` (fail-closed; no silent
     `repr` of unsupported types).
   - **Legacy / general JSON objects** → `canonical_json_bytes` / `cid_for_obj`
     where existing call sites already depend on that contract.
   - **Shared IR documents** → `ir-canonical-json-v1` (or a named successor
     profile) before CID assignment for IR artifacts.
2. **Default CID parameters for new content-addressed artifacts:** CIDv1,
   lowercase multibase `base32`, multihash `sha2-256`, codec `raw` or
   `dag-json` as appropriate. Call sites that need other codecs must document
   why and still validate with an explicit allowlist.
3. **Validate before trust.** Inbound CID strings used as contract fields must
   pass profile validation (e.g. `validate_cid`) rather than accepting any
   multiformat-looking string.
4. **Provenance records lineage, not content equality.** Provenance managers
   record sources, transformations, merges, filters, and related events and may
   link records to CIDs or IPLD storage. Lineage answers *how data was produced*;
   CIDs answer *what the bytes are*.
5. **Storage and location are orthogonal.** Pins, paths, gateway URLs, IPNS
   names, and router backends are **locations or transports**. Resolving a CID
   through a backend proves availability on that backend at that time—not a
   change of identity.
6. **Hard non-identity rule (required by this ADR):**

   | Thing | What it is | What it is **not** |
   | --- | --- | --- |
   | **CID / content digest** | Identifier for canonical bytes (or block) under a codec/hash | A location, a receipt of work done, an authorization to act, or a proof of a claim |
   | **Canonical bytes** | The byte sequence identity is computed over | Authorization, proof, or “published” status |
   | **Provenance record / lineage graph** | Attributed history of operations and sources | Content identity by itself; authorization; cryptographic proof of semantic correctness |
   | **Receipt** (policy, benchmark, install, audit) | Evidence that a process ran under stated inputs/outputs | Content identity; authorization to perform new side effects |
   | **Authorization / capability grant** (UCAN, policy admit, dispatch) | Permission to perform an action | Proven by holding a CID or provenance row alone |
   | **Proof / attestation** (solver, ZKP, kernel receipt) | Independent verification of a claim | Established by hashing inputs alone |

   **Identifiers are not locations, receipts, authorizations, or proof.**
   Documentation, APIs, and agents must not collapse these kinds of truth
   ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) §2;
   dependency lifecycle §9 on feature degradation vs fail-closed trust).

7. **Optional dependency on multiformats does not optionalize identity rules.**
   When CID helpers cannot import `multiformats`, features that *require* CIDs
   degrade or fail at use time (see [ADR-002](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md));
   they must not invent non-canonical string IDs that are later labeled CIDs.
   Isolated protocols (e.g. benchmark content-addressing bridge) may reimplement
   the same byte and multiformats contract without package-root side effects.

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Location-based identity (URL/path/IPNS as primary key) | Familiar; easy to log | Breaks under replication, renames, multi-backend retrieval; confuses publish with content | Rejected: product is multi-backend and content-addressed |
| Opaque UUID / DB row IDs as sole identity | Simple generation | No integrity; no cross-system verification | Rejected as primary content identity; UUIDs may remain local record ids *linked to* CIDs |
| Non-canonical JSON hashing (pretty-print / unsorted keys) | Easy for humans | Non-reproducible digests; collision of “same” objects | Rejected for new protocol artifacts; fail-closed DAG-JSON preferred |
| Treat provenance graph as identity | Rich lineage UX | Graph mutation, missing edges, and non-byte fields do not equal content equality | Provenance complements CIDs; does not replace them |
| Treat CID presence as authorization or proof | Convenient for agents | Unsafe; conflates integrity with admission and verification | Explicitly forbidden by this ADR |
| Single global “hash everything as raw UTF-8 text” | One code path | Loses structure, set semantics, IR profiles, IPLD codec interoperability | Rejected; codec and profile are part of the identity contract |

## Consequences

### Positive

- Cross-module and cross-process equality of artifacts is defined and reviewable.
- IPFS backends can swap without changing artifact identity.
- Provenance, receipts, authorization, and proof remain distinguishable in docs
  and APIs—reducing agent and operator misinterpretation.
- IR and benchmark pipelines can pin digests for reproducible evaluation.
- New protocol work has a clear preferred path (`canonical_dag_json_bytes` +
  `cid_for_dag_json`).

### Negative

- Authors must choose and document the correct encoding profile; wrong profile
  yields a different CID for “the same” logical object.
- Strict DAG-JSON rejects convenient Python objects (e.g. non-finite floats),
  requiring explicit normalization.
- Optional `multiformats` means some environments cannot compute CIDs until the
  dependency is available.
- Multiple historical helpers (`canonical_json_bytes` vs DAG-JSON vs IR v1)
  require care when bridging legacy and new paths.

### Neutral / deferred

- Full unification of every historical hash helper under one module is
  incremental work, not a rewrite mandate of this ADR.
- Cryptographic signing of provenance records and IPLD storage of lineage are
  **optional enhancements** of provenance fidelity, not prerequisites for using
  CIDs.
- Layered authority, fail-closed mediation, and registry/adapters are separate
  decision families (later ADRs in `IPFSDOC-G032`).
- End-to-end storage/processing architecture guides own flow diagrams; this ADR
  owns *why* identity/provenance boundaries exist.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. **Content identity is content-addressed.** Primary portable identifiers for
   dataset/protocol artifacts are digests/CIDs of canonical bytes under a named
   profile—not filesystem paths, gateway URLs, or pin-set membership alone.
2. **Canonical encoding is part of the contract.** Changing separators, key
   order rules, codec, multihash, or CID version changes identity and requires
   an explicit migration or profile version bump.
3. **Identifiers ≠ locations.** A CID does not assert that content is pinned,
   reachable, or stored in a particular backend.
4. **Identifiers ≠ receipts.** Holding or logging a CID is not evidence that a
   pipeline stage completed successfully.
5. **Identifiers ≠ authorizations.** A CID or provenance id never grants side
   effects, policy admission, or UCAN-equivalent rights by itself.
6. **Identifiers ≠ proof.** Digesting inputs or outputs does not verify
   theorems, ZK statements, or semantic correctness.
7. **Provenance references identity; it does not replace it.** Lineage records
   should point at content ids (and operation metadata) when integrity matters.
8. **Validation before acceptance.** Contract surfaces that consume CIDs apply
   explicit validation (version/base/codec/multihash) rather than string shape
   heuristics alone.
9. **No synthetic “CID-like” labels.** When multiformats or backends are
   unavailable, features report unavailability or use clearly non-CID local
   handles—never strings that impersonate canonical CIDs.
10. **Kinds of truth stay labeled** in documentation and APIs: discovery,
    availability, capability, proof, authorization, and content identity are
    separate claims.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

How reviewers and agents check that the codebase and docs still honor this
decision:

```bash
# Preferred helpers and fail-closed DAG-JSON still present
rg -n 'canonical_dag_json_bytes|cid_for_dag_json|validate_cid|cid_for_bytes' \
  ipfs_datasets_py/utils/cid_utils.py

# IR canonical profile still named and dependency-light
rg -n 'ir-canonical-json-v1|CANONICAL_JSON_PROFILE' \
  ipfs_datasets_py/logic/ir_core/canonical.py

# Profile D / shared logic CID contract
rg -n 'dag-json|dag_json_cid|canonical_dag_json' \
  ipfs_datasets_py/logic/ipld_cid.py

# Provenance domain still distinct from pure hashing
test -s ipfs_datasets_py/analytics/data_provenance.py

# Focused unit tests when available (non-blocking if env lacks extras)
# pytest tests/ -q -k 'cid or canonical or provenance' --collect-only
```

Narrative compliance criteria:

1. New content-addressed protocol artifacts document which byte profile and CID
   parameters they use.
2. Guides and APIs do not describe a CID as a location, receipt, grant, or proof.
3. Provenance docs describe lineage and audit—not “the CID of the row is
   authorization.”
4. Simulated or fallback content handles (if any) are not labeled as production
   multiformats CIDs without validation.

## Scope

### Applies to

- Dataset and processor outputs intended for IPFS/IPLD storage or cross-process
  integrity.
- IR, policy, benchmark, and receipt artifacts that bind digests.
- Provenance and audit integrations that link lineage to content.
- MCP/CLI/Python surfaces that expose CIDs or provenance records.
- Documentation that explains identity, storage, or trust boundaries.

### Does not apply to

- Ephemeral in-memory handles used only within a single function call with no
  integrity claim.
- Human display names, dataset titles, or UI labels (must not be treated as
  content ids).
- External systems’ own identity schemes when only bridged (map explicitly;
  do not silently equate).
- Authorization policy engines and proof kernels (consume identities; governed
  by their own contracts and later ADRs).

## Current evidence (2026-08-03)

| Evidence | Path / note | Supports |
| --- | --- | --- |
| Canonical JSON + CID helpers | `ipfs_datasets_py/utils/cid_utils.py` | Decision details 1–3 |
| Fail-closed DAG-JSON validation | same (`_validate_dag_json_value`, `allow_nan=False`) | Strict profile for new artifacts |
| Profile D IPLD CID helpers | `ipfs_datasets_py/logic/ipld_cid.py` | CIDv1 / dag-json / sha2-256 |
| IR canonical JSON v1 | `ipfs_datasets_py/logic/ir_core/canonical.py` | IR identity without optional deps |
| Benchmark byte contract mirror | `benchmarks/logic_pipeline/content_addressing.py` | Same multiformats standard, hermetic import |
| Provenance lineage types | `ipfs_datasets_py/analytics/data_provenance.py` | SOURCE/TRANSFORM/MERGE/… graph |
| Enhanced provenance + IPLD options | `ipfs_datasets_py/analytics/data_provenance_enhanced.py` | Optional crypto / IPLD storage |
| MCP provenance tools | `ipfs_datasets_py/mcp_server/tools/provenance_tools/` | Tool surface over domain logic |
| Backend retrieval by CID | `ipfs_datasets_py/ipfs_backend_router.py` | Location/transport vs identity |
| Packaging | `pyproject.toml` / `setup.py` multiformats, provenance extras | Optional dependency reality |
| Authority kinds of truth | `docs/maintenance/SOURCE_AUTHORITY.md` | Non-collapse of identity/authz/proof |
| Lifecycle trust vs feature | `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` §9 | Fail-closed trust boundaries |
| System context | `docs/architecture/SYSTEM_CONTEXT.md` | Product surfaces using CIDs |

**Discrepancies / deferred gates:** Historical docs and dashboards sometimes
print “CID” next to path-like or simulated identifiers; treat implementation
helpers and validators as authority over marketing prose. Full pytest CID
coverage may require optional extras (`multiformats`); absence of extras is an
availability issue (ADR-002), not a license to redefine identity.

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-002-LAZY-OPTIONAL-CAPABILITIES.md](ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional multiformats/IPLD and probe ≠ capability |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | When CID libs load; trust vs feature degradation |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Surfaces that expose content addressing |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Kinds of truth; authority order |
| `ipfs_datasets_py/utils/cid_utils.py` | Canonical bytes and CID implementation |
| `ipfs_datasets_py/analytics/data_provenance*.py` | Provenance lineage implementation |
| Package-local MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` | MCP structure; not global content-identity authority |

## Notes / errata

- Package-local MCP ADRs (thin wrapper, dual-runtime, …) use a separate
  numbering tree under `mcp_server/docs/adr/`. This file is **global**
  `docs/architecture/decisions/ADR-001` and does not supersede those MCP ADRs.
- When the decisions index (`README.md` in this directory) is created by a later
  task, this ADR must appear with status `accepted` and a one-line summary.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted from current-tree evidence (`IPFSDOC-013`) |
