# IR family ownership, canonical identity, and provenance

| Field | Value |
| --- | --- |
| Interface | `IRFamilyArchitecture@1` |
| Task | `IPFSDOC-040` |
| Status | `canonical` |
| Owner | architecture / logic |
| Source of truth | `ipfs_datasets_py/logic/ir_core/`; `ipfs_datasets_py/logic/legal_ir/`; `ipfs_datasets_py/logic/security_ir/`; `ipfs_datasets_py/logic/intent_ir/`; `ipfs_datasets_py/logic/formalization/`; `ipfs_datasets_py/logic/submodule_registry.py`; `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md), [IR_FAMILY_OPERATIONS.md](../../guides/IR_FAMILY_OPERATIONS.md), [SECURITY_IR_MIGRATION.md](../../security_verification/SECURITY_IR_MIGRATION.md) |
| Review cadence | when `ir_core` contracts or domain package boundaries change |

## 1. Purpose

This guide answers: **who owns intermediate-representation (IR) contracts in
`ipfs_datasets_py.logic`, how declarations get stable content identity, how
provenance and evidence ground claims without becoming proof, and how
Legal / Security / Intent families share a domain-neutral kernel while
remaining non-interchangeable authority classes.**

It turns the landed IR family structure into stable architecture guidance.
Companion leaves (compilers and semantic round-trip, external provers,
governed authorization, result authority) build on this document and must not
redefine kernel identity or collapse authority kinds.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place new IR work, imports, and docs without inventing a second kernel |
| **Domain developer** | Extend Legal, Security, or Intent adapters while keeping identity stable |
| **Security / policy reviewer** | Distinguish declaration CIDs, run manifests, receipts, and authority classes |
| **Operator** | Prefer canonical imports; treat compatibility facades as temporary |

## 3. Scope and non-goals

### In scope

- Domain-neutral **inward kernel** (`logic.ir_core`) ownership and dependency
  direction.
- **Canonical UTF-8 JSON** (`ir-canonical-json-v1`) and **stable CIDs**
  (`ir-canonical-identity-v1`).
- Immutable **declaration / run / result / receipt** artifact roles.
- **Claims**, **evidence**, and **source grounding** contracts.
- **Legal IR**, **Security IR**, and **Intent IR** family ownership.
- **Logic submodule registry** as machine-readable topology.
- **Canonical direct imports** versus **compatibility-facade** migration.
- Explicit, **non-interchangeable** result-authority classes.

### Non-goals

- Formal compilation, decompilation, and semantic round-trip evaluation
  policy (later logic leaf).
- External prover install recipes, portfolio routing, or solver capability
  matrices (later logic leaf / security verification guides).
- Intent rollout stages and promotion thresholds
  ([IR_FAMILY_OPERATIONS.md](../../guides/IR_FAMILY_OPERATIONS.md)).
- Full Security legacy artifact inventory or phase gates
  ([SECURITY_IR_MIGRATION.md](../../security_verification/SECURITY_IR_MIGRATION.md)).
- GraphRAG index construction, embedding checkpoints, or SkillCenter ops
  runbooks (`intent_ir` package README and ops scripts).
- Treating a CID, provenance row, monitor result, evidence gate, policy
  decision, retrieval score, or model confidence as theorem authority.

## 4. Mental model

```text
                    ┌─────────────────────────────────────┐
                    │  ir_core  (domain-neutral kernel)   │
                    │  canonical · identity · provenance  │
                    │  claims · evidence · artifacts      │
                    │  diagnostics · schema registry      │
                    │  result / receipt protocols         │
                    └──────────────▲──────────────────────┘
                                   │ depends on (inward only)
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   ┌──────┴──────┐         ┌───────┴───────┐        ┌───────┴───────┐
   │  legal_ir   │         │  security_ir  │        │  intent_ir    │
   │  adapter +  │         │  declaration  │        │  schema +     │
   │  formalize  │         │  + results    │        │  adapters     │
   └──────┬──────┘         └───────┬───────┘        └───────┬───────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                    formalization / backends / pipelines
                    (orchestrate; do not own kernel identity)
```

**One kernel, three domain families, many backends.** Domains share envelope,
canonicalization, identity, provenance, claim, evidence, artifact, and result
**protocols**. They do **not** share ontology, default claims, or authority to
substitute one domain's verdict for another.

## 5. Domain-neutral inward kernel (`ir_core`)

### 5.1 Ownership

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/logic/ir_core/` |
| **Import** | `ipfs_datasets_py.logic.ir_core` (lazy leaf exports) |
| **Owns** | Canonicalization profile; identity profile; provenance and source refs; diagnostics; schema registry and migrations; solver-neutral claims/obligations; evidence refs; artifact/run manifests; backend/result/receipt protocols and authority kinds |
| **Does not own** | Legal/Security/Intent ontologies; GraphRAG; model runtimes; solver process invocation; MCP transport; storage pin sets |
| **Dependency rule** | `ir_core` must **not** import Legal, Security, Intent, GraphRAG, autoencoders, or solvers |

Package root is intentionally lazy: importing `ir_core` loads only the export
map. Leaf modules (`canonical`, `identity`, `provenance`, `claims`,
`evidence`, `artifacts`, `diagnostics`, `schema_registry`, `protocols`) own
the contracts and remain free of optional heavy dependencies.

### 5.2 Leaf modules (current tree)

| Module | Role | Representative symbols |
| --- | --- | --- |
| `canonical.py` | Deterministic JSON bytes | `CANONICAL_JSON_PROFILE`, `canonical_json_bytes`, `CollectionSchema`, `CollectionSemantics` |
| `identity.py` | Stable content identity / CID | `IDENTITY_PROFILE`, `CanonicalIdentity`, `canonical_identity`, `cid_v1` |
| `provenance.py` | Source and producer bindings without source bodies | `SourceRef`, `SourceSpan`, `Provenance`, `ProducerBinding`, `ConfigBinding` |
| `diagnostics.py` | Structured, content-addressable diagnostics | `Diagnostic`, `DiagnosticReport`, `canonical_diagnostics_bytes` |
| `claims.py` | Solver-neutral claims and obligations | `Claim` / `IRClaim`, `Assumption`, `ProofObligation` / `IRObligation` |
| `evidence.py` | External evidence references | `EvidenceRef`, `EvidenceKind`, `EvidenceRegistry` |
| `artifacts.py` | Immutable run manifests and integrity | `Artifact`, `ArtifactRole`, `ArtifactManifest`, `RunManifest` |
| `schema_registry.py` | Versioned schemas and deterministic migrations | `IRSchemaRegistry`, `SchemaSpec`, `MigrationReceipt` |
| `protocols.py` | Backend bounds and **authority-separated** results | `ProofResult`, `MonitorResult`, `EvidenceGateResult`, `PolicyDecision`, `AuthorityKind` |

### 5.3 Allowed dependency direction

```text
domain schema          -> ir_core
domain adapter         -> domain schema + ir_core + formalization protocols
backend adapter        -> backend protocol + optional solver
pipeline / orchestrator-> domain adapters + backends + artifact store
compatibility facade   -> new domain package  (never the reverse as authority)
```

`formalization/` supplies domain-neutral samples, views, compiler, and advisor
**ports**. Domain packages adapt corpus-specific types (for example Legal
samples) into those ports. Optional capabilities are discovered without
installing packages as a side effect
([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).

## 6. Canonical UTF-8 JSON and stable CIDs

Identity is a function of **canonical bytes under a declared profile**, not of
filesystem path, pin set, branch name, timestamp, or optional library
presence. This aligns with
[ADR-001 Content Identity and Provenance](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md).

### 6.1 Canonicalization profile (`ir-canonical-json-v1`)

Implemented in `logic.ir_core.canonical`. Rules:

| Rule | Behavior |
| --- | --- |
| Text | Unicode **NFC**; map keys are strings, unique after NFC, sorted by code point |
| Numbers | Finite decimals only; no NaN/infinity; no exponent form, insignificant zeroes, leading zeroes, or negative zero |
| Encoding | Compact JSON, lowercase literals, **UTF-8** bytes |
| Sequences | **Ordered** by default; schema may declare **set-like** (sorted, deduped) or **multiset** (sorted, duplicates kept) via JSON Pointer rules |
| Dependencies | **None** — optional CID libraries must not change bytes |

Collection semantics are part of the identity preimage when declared (for
example `SECURITY_IR_COLLECTION_SCHEMA`, `INTENT_IR_COLLECTION_SCHEMA`).
Undeclared sequences remain ordered unless a schema sets
`require_declared=True`.

### 6.2 Identity profile (`ir-canonical-identity-v1`)

Implemented in `logic.ir_core.identity`. Fixed wire profile:

| Parameter | Value |
| --- | --- |
| Profile name | `ir-canonical-identity-v1` |
| Canonicalization | `ir-canonical-json-v1` |
| Digest | SHA-256 (`sha2-256`, multihash code `0x12`) |
| CID version | CIDv1 |
| Multicodec | `raw` (`0x55`) |
| Multibase text | unpadded lowercase base32 (`b…`) |

The identity preimage is a canonical JSON envelope binding:

- canonicalization profile name;
- **IR domain** string (for example `legal`, `security-ir`, Intent schema
  domain);
- **schema version**;
- collection-semantics declaration;
- the declarative **payload**.

`CanonicalIdentity` exposes both `digest` (`sha256:…`) and `cid` (CIDv1 text).
The textual **identifier** is the CID string. CID bytes are assembled from
fixed multiformat codes **without importing optional multiformats packages**,
so installing or removing those packages cannot change an IR identifier.

### 6.3 What identity is not

| Thing | Is | Is **not** |
| --- | --- | --- |
| **CID / digest** | Identifier of canonical bytes under the profile | Location, receipt, authorization, or proof of a claim |
| **Canonical bytes** | The exact preimage of identity | “Published”, “approved”, or theorem status |
| **Provenance record** | Lineage and source binding | Content equality alone; authorization; semantic proof |
| **Run / artifact manifest** | Binding of inputs, parents, outputs, producers, configs | Permission to promote or execute |
| **Proof receipt** | Evidence a backend checked an obligation under bounds | Established by hashing the declaration alone |
| **Policy / admissibility decision** | Release or dispatch evaluation | Interchangeable with theorem proof |

**Identifiers are not locations, receipts, authorizations, or proof.** Agents
and APIs must keep these kinds of truth distinct.

### 6.4 Domain identity constants (current tree)

| Family | Domain / schema markers | Package |
| --- | --- | --- |
| Kernel artifacts | `ir.artifact-manifest`, `ir-artifact-manifest/v1` | `ir_core.artifacts` |
| Legal formalization | `LEGAL_IR_DOMAIN = "legal"` | `legal_ir.adapter` |
| Security declarations | `SECURITY_IR_IDENTITY_DOMAIN = "security-ir"`, schema `SECURITY_IR_*_SCHEMA_VERSION` | `security_ir.model` |
| Intent documents | `INTENT_IR_SCHEMA_VERSION = "intent-ir/v1"` (legacy `intent-ir/v0.1`) | `intent_ir.schema` |

Domain and schema version are part of the identity preimage: two equal
payloads under different domains or schema versions are different identities.

## 7. Immutable declaration, run, result, and receipt artifacts

### 7.1 Separation of concerns

A single mutable object that mixes declarations, solver logs, runtime traces,
and reports is a design failure. The family enforces **immutable roles**:

| Role | Meaning | Identity impact |
| --- | --- | --- |
| **Declaration** | Domain IR document (principals, policies, intent statements, legal views, …) | Stable; **must not change** when solvers run or optional libraries appear |
| **Run** | One pipeline execution bound by `ArtifactManifest` / `RunManifest` | New identity per run; parents include declaration digests |
| **Result** | Typed outcome of a query kind (`ProofResult`, `MonitorResult`, …) | Binds declaration + obligation + backend + assumptions + bounds |
| **Receipt** | Issued record of a result and authority (`ProofReceipt`, result receipts) | Binds result digests; not a new declaration |

Security IR makes this explicit: `SecurityIR` holds **only** declarations;
verification runs, runtime traces, disproof vectors, evidence gates, release
decisions, and proof receipts are **separate** immutable records
(`security_ir.results`).

### 7.2 Artifact roles in a run

`ArtifactRole` in `ir_core.artifacts`:

| Role | Use |
| --- | --- |
| `input` | Declared inputs consumed by the run |
| `parent` | Prior artifacts this run derives from |
| `output` | Deterministic products of the run |
| `diagnostic` | Diagnostics and non-authoritative observations |

Paths in manifests are portable, **root-relative POSIX** paths. Integrity
verification is fail-closed and may reject unbound files under the artifact
root.

### 7.3 Manifest: deterministic vs observational

Each `ArtifactManifest` has two layers:

| Layer | Contents | In identity? |
| --- | --- | --- |
| **Deterministic** | Artifact digests/CIDs, lineage, producers, configs, schema/ontology/tool/model/solver versions, prompt-template digests, diagnostics IDs, reviewed decisions | **Yes** — feeds `manifest_id` / output identity |
| **Observations** | Clocks, durations, host/environment, resource usage | **No** — preserved for ops, excluded from identity |

Reviewed decisions use `DecisionKind`: `review`, `license`, `trust`. They
constrain use or promotion; they are not theorem authority.

### 7.4 Typical lifecycle

1. Validate and freeze a **declaration**; compute identity.
2. Write bounded outputs under `runs/<run-id>/` with a unique run identity.
3. Build an immutable **manifest** binding parents, tools, and digests.
4. Issue typed **results** / **receipts** for each obligation attempt.
5. Promote only by **immutable copy** into a reviewed `promoted/` layout with
   a new parent-bound manifest — never mutate promoted bytes in place.

Do not use timestamps, branch names, `main`, `latest`, directory mtimes, or
bare filenames as identity.

## 8. Claims, evidence, and source grounding

### 8.1 Claims and obligations (solver-neutral)

`ir_core.claims` describes **what is claimed** and **what must be checked**
without embedding solver objects or verdicts:

| Contract | Schema version (current) | Role |
| --- | --- | --- |
| Claim / `IRClaim` | `ir-claim/v1` | Declarative property under assumptions |
| Assumption / `IRAssumption` | `ir-assumption/v1` | Explicit premises (not silent defaults) |
| Proof obligation / `IRObligation` | `ir-proof-obligation/v1` | Solver-neutral check request |

Backend compilers lower obligations to Z3, cvc5, SMT-LIB, Lean, Coq, or other
targets. Portfolio order records every attempt; policy selects the accepted
result without rewriting the claim identity.

### 8.2 Evidence (referenced, not embedded)

`ir_core.evidence` binds **external bytes** by digest/CID:

| Field concept | Role |
| --- | --- |
| `EvidenceRef` | Stable `evidence_id`, kind, `content_sha256`, optional CID/URI |
| `EvidenceKind` | `source`, `artifact`, `test_result`, `proof_receipt`, `runtime_observation`, `review`, `attestation`, `model_output`, `other` |
| `EvidenceReviewStatus` | Lifecycle (`unreviewed` … `quarantined`) — **not** proof authority |

**Evidence never grants theorem, trust, execution, or policy authority by
itself.** Consumers interpret `kind` and `review_status` under an explicit
policy. Model outputs and runtime observations remain first-class evidence
kinds without becoming proofs.

### 8.3 Provenance and source grounding

`ir_core.provenance` identifies source bytes and tool/configuration bindings
**without** embedding source text, prompts, logs, or model responses:

| Contract | Role |
| --- | --- |
| `SourceRef` | URI, source-native id, immutable revision, `content_sha256`, optional container digest/CID, license expression, review status |
| `SourceSpan` | Inclusive-exclusive byte span on a `SourceRef` |
| `ProducerBinding` / `ConfigBinding` | Tool and configuration identities by digest |
| `Provenance` | Aggregated bindings for a document or artifact |

Source review status (`unreviewed`, `machine_extracted`, `human_reviewed`,
`trusted_fixture`, `quarantined`, `rejected`) is **not** policy or proof
authority.

**Grounding rule:** every assertion, action, relation, and formula that
claims source grounding must bind one or more stable source references (and
spans when available). GraphRAG retrieval, embeddings, and learned candidates
are separately versioned artifacts; they may cite source digests but do not
replace source refs as the grounding contract.

Intent IR enforces grounding in-document (`NodeGrounding`, `GroundingKind`,
`SourceRef` / `SourceSpan` on `IntentIRDocument`). Legal and Security adapters
carry source maps and extension vocabulary through their domain contracts
while reusing kernel provenance types where applicable.

### 8.4 Diagnostics

Diagnostics are structured, content-addressable, source-mapped where
possible, and assigned stable codes (`ir_core.diagnostics`). Warnings cannot
silently become successful proofs. Cross-reference validation fails closed on
dangling IDs.

## 9. Result authority classes (non-interchangeable)

`ir_core.protocols` defines **closed, intentionally non-hierarchical**
authority kinds. Result types pin an expected authority; mismatches raise
`AuthorityMismatchError`.

### 9.1 Authority kinds

| `AuthorityKind` | Meaning | May claim theorem authority? |
| --- | --- | --- |
| `theorem_proof` | Formal property checked under explicit assumptions and configured proof policy | **Only** under that policy and a valid proof result/receipt |
| `satisfiability` | Model existence / satisfiability | **No** |
| `runtime_monitor` | Bounded runtime trace observation | **No** |
| `evidence_readiness` | Required evidence present or blocked | **No** |
| `policy_approval` | Release/security policy evaluation | **No** |

`QueryKind` mirrors these values and maps 1:1 to `AuthorityKind`. Descriptive
aliases (`PROOF`, `EVIDENCE_GATE`, …) are spelling helpers only; they do not
create new authority.

### 9.2 Result families

| Result type | `result_type` | Expected authority |
| --- | --- | --- |
| `ProofResult` | `proof` | `theorem_proof` |
| `SatisfiabilityResult` | `satisfiability` | `satisfiability` |
| `MonitorResult` | `runtime_monitor` | `runtime_monitor` |
| `EvidenceGateResult` | `evidence_gate` | `evidence_readiness` |
| `PolicyDecision` | `policy_decision` | `policy_approval` |

Security IR re-exports parallel typed results (`security_ir.results`) and
selection policy (`security_ir.result_policy`) that **preserve** family
boundaries: for example an Xaman evidence-readiness / blocker query maps to
an evidence gate or satisfiability family, **never** silent theorem proof.

### 9.3 Hard non-substitution rules

- A high retrieval score, advisor confidence, monitor pass, evidence gate
  pass, or policy admit **cannot** be relabeled as theorem proof.
- Unavailable or unsupported backends yield typed unavailable/unsupported
  attempts; they do not fall through to another result family.
- Simulated or mock ZKP paths are never production-authoritative (see
  `proof_corpus` registry notes).
- `ResultAuthority` records kind, issuer, method, scope digest, and evidence
  digests — it is not interchangeable across kinds.

## 10. Domain families

### 10.1 Shared envelope expectations

Domain documents share stable protocol concerns even when field vocabularies
differ:

- domain and schema version;
- stable document / declaration identity;
- canonical declarative payload;
- source-reference identifiers;
- extension vocabulary identifiers;
- producer and configuration identities;
- parent artifact identities;
- review state.

Raw source text, embeddings, model responses, solver logs, runtime traces, and
narrative reports live in **separate** artifacts.

### 10.2 Legal IR (`legal_ir`)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/logic/legal_ir/` |
| **Canonical import** | `ipfs_datasets_py.logic.legal_ir` |
| **Role** | Legal formalization **adapter** over shared formalization contracts; canonical compiler / decompiler / round-trip contracts for deontic and related views |
| **Domain marker** | `LEGAL_IR_DOMAIN = "legal"` |
| **Key surfaces** | `LegalIRAdapter`, `LegalIRFormalizationAdapter`, `CanonicalCompiler` / decompiler / round-trip types, constraint query and proof cache helpers |
| **Does not own** | Kernel identity profiles; Security declarations; Intent skill execution |

Legal-specific corpus assumptions (for example US-code sample constraints in
legacy loops) stay in Legal adapters. Intent and Security must consume
**generic** formalization samples/ports, not Legal-only types.

Historical Legal modules outside `legal_ir/` (compiler API, pass manager,
diagnostics under broader `logic/`) remain compatibility or specialized
surfaces; **new** work prefers `legal_ir` + `ir_core` contracts.

### 10.3 Security IR (`security_ir`)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/logic/security_ir/` |
| **Canonical import** | `ipfs_datasets_py.logic.security_ir` |
| **Role** | Immutable security **declarations**, domain adapters (exchange, Xaman), typed results, result policy, formalization adapter, artifact migration helpers |
| **Domain marker** | `SECURITY_IR_IDENTITY_DOMAIN = "security-ir"` |
| **Key surfaces** | `SecurityIR` / `SecurityIRV1`, principals/assets/policies/claims, `LegacySecurityIRAdapter`, `ProofResult` / `EvidenceGateResult` / …, `select_authoritative_result` |
| **Does not own** | Wallet UCAN grants (`wallet`); MCP auth tools alone; kernel CID profile |

**Invariant:** declaration identity is independent of verification execution
and optional solver/CID library installation. Caller-owned mutable
collections are copied at the adapter boundary; never retained.

Domain adapters:

- `security_ir/exchange` — exchange-specific vocabulary and defaults;
- `security_ir/xaman` — Xaman task IDs, evidence readiness, reports.

Unknown vocabulary requires a declared vocabulary ID/version, namespaced
terms, adapter validation, and fail-closed behavior when the adapter is
unavailable.

### 10.4 Intent IR (`intent_ir`)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/logic/intent_ir/` |
| **Canonical import** | `ipfs_datasets_py.logic.intent_ir` |
| **Role** | Source-grounded semantic boundary between skill corpora, GraphRAG projections, and formal-logic compilers |
| **Schema** | `intent-ir/v1` (migration from `intent-ir/v0.1`) |
| **Key surfaces** | `IntentIRDocument`, `IntentStatement`, `IntentAction`, `decode_intent_ir`, `canonical_intent_ir_bytes`, ports in `protocols.py` |
| **Subpackage** | `intent_ir.invocation` — invocation envelopes; SkillCenter/prompt/MCP adapters that are **non-executing** |
| **Does not own** | Command execution found in skills; proof authority for retrieved context |

**Hostile input rule:** source text and commands are quoted data. No Intent
stage executes, imports, or installs anything found in a source record.
Learned formalization advisors propose candidates; they are not authority for
provenance, schema validity, proof, trust, or permission to execute a skill.

Intended content-addressed chain (identities are CIDs/digests, not paths):

```text
pinned corpus snapshot
  -> raw bundle / record digests
  -> validated IntentIRDocument identity
  -> GraphRAG / formal-logic projection identities
  -> proof or evaluation receipt identities
```

Each arrow retains parent identity, producer version, configuration digest,
diagnostics, and review state.

### 10.5 Formalization and backends (adjacent)

| Package | Role relative to families |
| --- | --- |
| `logic.formalization` | Domain-neutral samples, views, compiler, advisor, evaluation ports |
| `logic.backends` | Solver adapters implementing kernel backend protocols |
| `logic.external_provers` | Lazy external prover routing (Z3, CVC5, Lean, Coq, …) |
| `logic.admissibility` | Authorization gates and rollout receipts — **policy**, not theorem proof |
| `logic.proof_corpus` | Attested proofs, revocation, trust policy bindings |

These packages **consume** family declarations and kernel protocols; they do
not redefine `ir-canonical-json-v1` or `ir-canonical-identity-v1`.

## 11. Logic submodule registry

### 11.1 Role

`ipfs_datasets_py.logic.submodule_registry` is the **machine-readable
topology** of the logic package: names, module paths, roles, public symbols,
optional dependencies, and import-check flags. It is **not** the same as git
submodules under `.gitmodules`
([INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md)).

Public helpers:

- `logic_submodule_specs()`, `logic_submodule_names()`, `logic_submodule_spec(name)`
- `logic_integration_manifest()`, `logic_submodule_import_report()`

### 11.2 IR-family registry entries (authoritative names)

| Registry name | Module | Notes |
| --- | --- | --- |
| `ir_core` | `ipfs_datasets_py.logic.ir_core` | Dependency-light foundation |
| `formalization` | `ipfs_datasets_py.logic.formalization` | Domain-neutral formalization ports |
| `legal_ir` | `ipfs_datasets_py.logic.legal_ir` | Legal formalization adapter |
| `security_ir` | `ipfs_datasets_py.logic.security_ir` | Immutable Security IR |
| `intent_ir` | `ipfs_datasets_py.logic.intent_ir` | Source-grounded Intent IR |
| `intent_ir.invocation` | `…intent_ir.invocation` | Non-executing invocation adapters |
| `security_models` | `ipfs_datasets_py.logic.security_models` | Legacy exchange-style models (compat) |
| `tools` | `ipfs_datasets_py.logic.tools` | **Deprecated** → `integration` |

Registry discovery and capability probes must remain **side-effect free**: no
solver install, process start, or file write as a mere consequence of listing
submodules.

## 12. Canonical direct imports

Prefer **direct package imports** of the owning module. Do not import through
deprecated facades for new code.

### 12.1 Preferred imports

```python
# Kernel
from ipfs_datasets_py.logic.ir_core import (
    canonical_json_bytes,
    canonical_identity,
    SourceRef,
    Claim,
    EvidenceRef,
    ArtifactManifest,
    ProofResult,
    AuthorityKind,
)

# Domain families
from ipfs_datasets_py.logic.legal_ir import LegalIRAdapter
from ipfs_datasets_py.logic.security_ir import SecurityIR, adapt_legacy_security_ir
from ipfs_datasets_py.logic.intent_ir import IntentIRDocument, decode_intent_ir

# Topology
from ipfs_datasets_py.logic.submodule_registry import logic_submodule_names
```

Leaf modules remain valid when you need a narrow dependency surface:

```python
from ipfs_datasets_py.logic.ir_core.identity import IDENTITY_PROFILE
from ipfs_datasets_py.logic.ir_core.protocols import EvidenceGateResult
```

### 12.2 Import policy notes

- `ir_core` package `__getattr__` resolves exports lazily; avoid star-imports
  that force every leaf.
- Domain packages similarly lazy-load where cycles with legacy namespaces
  exist (`security_ir` vs `security_models.crypto_exchange`).
- Default package import hermeticity for `ipfs_datasets_py` still applies:
  heavy stacks stay behind explicit init / extras
  ([DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md)).

## 13. Compatibility-facade migration

### 13.1 Strategy

The IR family uses a **strangler** migration: new code and identity live under
canonical packages; old imports and artifacts remain readable through
**facades** until a documented deprecation window ends. Facades **adapt**; they
are not a second source of semantic truth.

### 13.2 Security IR facade

| Surface | Status |
| --- | --- |
| `logic.security_ir` | **Canonical** declarations, adapters, results |
| `logic.security_models.crypto_exchange` | **Frozen compatibility** namespace; marked deprecated |

Legacy adapter APIs (`LegacySecurityIRAdapter`, `adapt_legacy_*`,
`to_legacy_*`) copy and classify; they do **not**:

- delete source artifacts;
- rewrite a legacy ID in place;
- select release evidence;
- grant theorem authority;
- change declaration identity when verification runs.

Migration phases (`inventory` → `dual-read` → `v1-write` → `v1-default` →
`legacy-removal`) and removal gates are specified in
[SECURITY_IR_MIGRATION.md](../../security_verification/SECURITY_IR_MIGRATION.md).
Legacy identifiers are retained as `legacy_id` values in migration manifests;
they are never silently rewritten into CIDs of a different profile.

### 13.3 Intent IR schema migration

Intent IR registers deterministic migrations (for example
`INTENT_IR_V0_1_TO_V1_MIGRATION_ID`) through decode helpers
(`decode_intent_ir_with_migration`, `migrate_intent_ir`). Migration receipts
and loss reports use kernel schema-registry patterns: nondeterministic or
lossy upgrades fail closed or quarantine for review.

### 13.4 Legal and tools facades

- Older Legal surfaces under broader `logic/` may still be imported by
  historical callers; **new** formalization work targets `legal_ir` +
  `formalization` + `ir_core`.
- `logic.tools` is a **deprecated compatibility** path; migrate to
  `logic.integration`. Deprecation warnings and v2.0 removal intent are
  encoded at the package boundary.

### 13.5 Deprecation window principles

Aligned with the Security migration policy:

- at least two consecutive minor releases **and** 180 days after the first
  published warning (whichever ends later), plus measured downstream
  migration and explicit removal approvals;
- only coordinated integration tasks edit package `__init__.py`,
  `submodule_registry.py`, or shared CLI registration for cutovers;
- golden legacy round-trips and identity-binding tests gate facade changes.

## 14. Cross-cutting invariants (checklist)

1. **Inward kernel:** `ir_core` never imports domain packages or solvers.
2. **Stable declaration identity:** solvers, timestamps, and optional CID
   libraries do not change declaration digests/CIDs.
3. **Canonical bytes first:** equality uses `ir-canonical-json-v1` (or a named
   successor) before hashing.
4. **CID profile fixed:** `ir-canonical-identity-v1` parameters are part of the
   contract, not ambient library defaults.
5. **Separate artifact roles:** declaration ≠ run ≠ result ≠ receipt.
6. **Ground claims:** source-grounded assertions bind `SourceRef` / spans;
   evidence refs do not embed hostile bodies into semantic IR.
7. **Authority non-substitution:** proof, satisfiability, monitor, evidence
   gate, and policy results remain distinct types and kinds.
8. **Fail closed:** missing, stale, mismatched, unlicensed, or unreviewed
   evidence blocks promotion; it does not soft-succeed as proof.
9. **Canonical imports:** new code uses `legal_ir` / `security_ir` /
   `intent_ir` / `ir_core` directly; facades are temporary.
10. **Registry truth:** topology questions answer from
    `submodule_registry`, not from ad hoc directory listing alone.

## 15. Worked identity sketch

```text
SecurityIR declaration (immutable)
  -> canonical_json_bytes(payload, collection_schema=SECURITY_IR_COLLECTION_SCHEMA)
  -> identity envelope { profile, domain="security-ir", schema_version, collections, payload }
  -> sha256 + CIDv1 (raw)  == declaration_id

Verification run
  -> ArtifactManifest(parents=[declaration_id, …], tools, configs, outputs)
  -> manifest_id  (observations excluded)

Obligation attempt
  -> BackendAttempt + ProofResult | EvidenceGateResult | …
  -> ProofReceipt binds result digests + ResultAuthority(kind=…)

Promotion
  -> new content-addressed artifact + parent digests + human review decision
  -> never mutates declaration_id
```

Intent and Legal follow the same **shape** with their own domain/schema
markers and payloads.

## 16. Related documents

| Document | Relationship |
| --- | --- |
| [ADR-001 Content Identity and Provenance](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Product-wide CID vs provenance vs proof rules |
| [ADR-003 Layered Authority](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Cross-cutting authority layering |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2 | Logic package ownership and registry table |
| [IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md](../IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md) | Program plan and target package layout |
| [IR_FAMILY_OPERATIONS.md](../../guides/IR_FAMILY_OPERATIONS.md) | Rollout stages, promotion gates, SkillCenter pinning |
| [SECURITY_IR_MIGRATION.md](../../security_verification/SECURITY_IR_MIGRATION.md) | Security strangler phases and deprecation |
| `ipfs_datasets_py/logic/intent_ir/README.md` | Intent scaffold and ops chain |
| Later leaves (planned) | Compilers / semantic round-trip; external provers; governed authorization; result authority deep dive |

## 17. Verification hints

Registry and export smoke (from repository root, when the package is
importable):

```bash
python3 -c "from ipfs_datasets_py.logic.submodule_registry import logic_submodule_names; print('ir_core' in logic_submodule_names())"
python3 -c "from ipfs_datasets_py.logic.ir_core import IDENTITY_PROFILE_NAME, CANONICAL_JSON_PROFILE; print(CANONICAL_JSON_PROFILE, IDENTITY_PROFILE_NAME)"
```

Focused integration suites (when exercising the family, not required to
validate this document alone):

```bash
python -m pytest \
  tests/integration/logic/test_ir_compatibility_exports.py \
  tests/integration/logic/test_ir_family_conformance.py -q
```

## 18. Change control

- Behavioral meaning of `IRFamilyArchitecture@1` changes only with a reviewed
  revision of this document and matching kernel/domain contracts.
- New domain families must register in `submodule_registry`, depend inward on
  `ir_core`, declare collection schemas and domain markers, and keep result
  authority kinds uncollapsed.
- Compatibility removals require the documented deprecation window and
  migration evidence; do not delete facades “because CI is green.”
