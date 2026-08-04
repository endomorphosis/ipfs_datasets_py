# Glossary and authority vocabulary

| Field | Value |
| --- | --- |
| Interface | `DocumentationGlossary@1` |
| Task | `IPFSDOC-093` |
| Status | `canonical` |
| Owner | documentation-governance / navigation |
| Source of truth | Architecture leaves under `docs/architecture/` (especially logic, runtime, system context); ADRs under `docs/architecture/decisions/`; `docs/maintenance/SOURCE_AUTHORITY.md`; implementation under `ipfs_datasets_py/logic/`, routers, and packaging |
| Last verified | 2026-08-03 |
| Audience | all (primary: architect, developer, agent) |
| Related | [SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md), [ADR-003 Layered authority](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-001 Content identity](architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-004 Fail-closed degradation](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md), [IR_FAMILY_AND_IDENTITY.md](architecture/logic/IR_FAMILY_AND_IDENTITY.md), [RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md), [GOVERNED_AUTHORIZATION.md](architecture/logic/GOVERNED_AUTHORIZATION.md), [PROOF_ATTESTATION_AND_ZKP.md](architecture/logic/PROOF_ATTESTATION_AND_ZKP.md), [END_TO_END_DATA_FLOW.md](architecture/END_TO_END_DATA_FLOW.md), [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md), [SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md) |
| Review cadence | when authority kinds, IR profiles, or product surfaces change |

## Purpose

This glossary is the **shared vocabulary** for IPFS Datasets Python
(`ipfs_datasets_py`). It defines project-specific terms, separates commonly
collapsed identity / evidence / authority / runtime states, and names
canonical aliases versus deprecated labels. Definitions are grounded in
current architecture and implementation—not general-purpose dictionary
senses.

**Rules for authors and agents**

1. Prefer the **canonical term** in new docs and APIs; mention aliases only as migration aids.
2. Never promote an earlier authority layer’s result into a later layer by renaming status fields.
3. Cite architecture leaves or ADRs when a claim is normative; this page summarizes, it does not supersede tests or code.
4. Expand only acronyms that this product uses as named contracts; do not invent expansions.

---

## Hard inequalities (do not collapse)

These inequalities are program invariants
([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) §2;
[ADR-003](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md)):

| Inequality | Meaning in this product |
| --- | --- |
| Discovery ≠ capability | Importable, registered, or listed ≠ demonstrated working operation |
| Capability ≠ authorization | A successful probe or tool call ≠ permission to perform side effects |
| Syntax ≠ semantics | Parses under a grammar/schema ≠ domain-valid or policy-valid |
| Model / retrieval output ≠ proof | LLM drafts, search hits, GraphRAG nodes are candidates only |
| Satisfiability ≠ theorem proof | SAT/UNSAT under a model is its own `AuthorityKind`, not theorem authority |
| Proof ≠ authorization | Attested or proved formula does not grant execution |
| Policy ≠ authorization | Policy approval is not an allow decision unless the authz path says so |
| Authorization ≠ dispatch | Allow does not mean the tool already ran |
| Monitoring ≠ proof | Telemetry, dashboards, circuit breakers are observations |
| Receipt presence ≠ success of the claim | A stored receipt records what was decided or attempted; re-check digests |
| CID ≠ location / pin / authorization | Content identity is not where content lives, nor permission to act |
| Provenance ≠ proof | Lineage bindings are not theorem or authorization authority |
| Empty submodule path ≠ feature complete | Path existence is not capability evidence |
| Stub / fallback success ≠ production quality | Degraded paths must stay labeled |

---

## Layered authority stack

Order is **feed-forward only**. Later layers may consume digests, CIDs, and
typed results from earlier layers; they never silently rewrite earlier truth
kinds ([ADR-003](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md)).

| Order | Layer | Establishes | Does **not** establish |
| ---: | --- | --- | --- |
| 1 | **Parsing** | Structure accepted by grammar/schema | Meaning, truth, permission |
| 2 | **Validation** | Semantic / integrity constraints for a profile | Theorem truth; side-effect rights |
| 3 | **Retrieval / model candidates** | Ranked or generated candidates | Proof, policy admit, execution rights |
| 4 | **Satisfiability** | SAT/UNSAT (or equivalent) under explicit assumptions | Theorem under another encoding; production security of the unmodeled world |
| 5 | **Proof** | Formal check or attestation under a declared `result_authority` | Authorization to act |
| 6 | **Policy** | Release / license / security / product rule evaluation | Theorem authority; automatic remote side effects |
| 7 | **Authorization** | Action class **allow** / **reject** / **abstain** under a profile | That the action already ran |
| 8 | **Dispatch** | Control-plane invocation of a tool/API | That invocation was authorized; that outputs are proofs |
| 9 | **Monitoring** | Runtime telemetry and health signals | Safety proofs; authorization |
| 10 | **Receipts** | Immutable, often content-addressed record of claim/decision/run | Promotion of weak evidence to strong authority by mere storage |

---

## Kinds of truth (documentation and runtime claims)

Use these labels when a page mixes claim types
([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) §2):

| Kind | Question answered |
| --- | --- |
| **Discovery** | Is it importable, registered, or listed? |
| **Availability** | Is the dependency/backend present on this machine? |
| **Capability** | Was a successful probe or operation demonstrated? |
| **Syntax validity** | Does structure parse? |
| **Semantic / policy validity** | Do meaning and admission rules hold? |
| **Proof** | Did an external prover or attestation succeed under a declared authority kind? |
| **Authorization** | Are side effects allowed under the active profile and roots? |
| **Canonical vs compatibility** | Preferred path versus alias/deprecated surface |
| **Preferred / optional / stub** | Complete path vs optional vs incomplete/degraded |

---

## Identity, content addressing, and lineage

### CID (Content Identifier)

Portable **content address** of canonical bytes (or an IPLD block) under a
declared encoding profile. Default new-work parameters in this product: **CIDv1**,
`sha2-256`, multicodec `raw` or `dag-json`, lowercase base32 text
([ADR-001](architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md);
`utils.cid_utils`, `logic.ir_core.identity`).

A **CID** is **not**: a filesystem path, HTTP URL, pin-set membership, IPNS
name, proof, policy decision, authorization grant, or receipt of success.

### Canonical bytes / canonicalization profile

Deterministic byte encoding before hashing. Product profiles include:

| Profile | Role |
| --- | --- |
| Exact bytes + `raw` | Opaque payloads |
| `canonical_dag_json_bytes` / DAG-JSON | Fail-closed structured objects (no NaN/`repr` fallbacks) |
| `canonical_json_bytes` | Legacy/general JSON object path |
| `ir-canonical-json-v1` | IR-family documents (NFC keys, finite decimals, collection semantics) |

Identity is a function of **canonical bytes under a named profile**, not of
branch name, mtime, install path, or optional library presence.

### Canonical identity (`ir-canonical-identity-v1`)

IR kernel profile binding domain string, schema version, collection semantics,
and payload into a digest and CIDv1 (`logic.ir_core.identity`). Equal payloads
under different domains or schema versions are **different** identities.

### Digest

Cryptographic hash of canonical bytes (commonly `sha256:…` or multihash).
Often paired with a CID; neither is a location nor a permission.

### Provenance

**Lineage** that binds sources, producers, transforms, and content identities.
Three **non-interchangeable** layers appear in product flows
([END_TO_END_DATA_FLOW.md](architecture/END_TO_END_DATA_FLOW.md)):

| Layer | Home | Role |
| --- | --- | --- |
| **Operational lineage** | `analytics` `ProvenanceManager` | SOURCE / TRANSFORM / MERGE / QUERY / RESULT records; optional IPLD chains |
| **IR provenance** | `logic.ir_core.provenance` (`SourceRef`, digests, `ir-provenance/v1`) | Source-body-free identity for semantic IR |
| **Proof / authz evidence** | `logic.proof_corpus`, `logic.admissibility` | Attested envelopes, decision receipts—still **not** automatic allow |

Provenance **references** identities; it does not replace content addressing or
prove theorems.

### Declaration / run / result / receipt (artifact roles)

Immutable role separation for IR and security pipelines
([IR_FAMILY_AND_IDENTITY.md](architecture/logic/IR_FAMILY_AND_IDENTITY.md)):

| Role | Meaning |
| --- | --- |
| **Declaration** | Domain IR document; stable when solvers run |
| **Run** | One pipeline execution (`ArtifactManifest` / `RunManifest`) |
| **Result** | Typed outcome for a query kind (`ProofResult`, `MonitorResult`, …) |
| **Receipt** | Issued record binding result digests and authority; not a new declaration |

Manifests split **deterministic** fields (in identity) from **observations**
(clocks, host metrics—out of identity).

### Pin / location / IPNS

Storage and naming concerns. **Pinning** retains content at a node; **location**
is where bytes were last seen; **IPNS** is a mutable name. None of these equal
content identity, proof, or authorization.

---

## Evidence, proof, policy, authorization, and receipts

### Evidence / EvidenceRef

External support for a claim (documents, digests, corpus rows) without
embedding solver objects (`logic.ir_core.evidence`). **Evidence readiness**
(`AuthorityKind.evidence_readiness`) answers whether required evidence is
present and well-formed—not whether a theorem holds or an action is allowed.

### Claim / obligation

Solver-neutral statements of **what is asserted** (`IRClaim`) and **what must
be checked** (`IRObligation`) under explicit assumptions. Compilers lower
obligations to provers; claim identity does not change when backends change.

### Proof

A formal property checked or attested under a declared **result authority** and
**attestation kind**. Production paths use `logic.proof_corpus` envelopes and
independent consumer verification. **Simulation** and
**artifact-membership** attestation kinds never become production theorem
authority under strict profiles
([PROOF_ATTESTATION_AND_ZKP.md](architecture/logic/PROOF_ATTESTATION_AND_ZKP.md)).

### Result authority (`AuthorityKind`)

Closed, **non-hierarchical** kinds on trust-bearing results
([RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md);
`logic.ir_core.protocols`):

| Kind | Semantic question |
| --- | --- |
| `theorem_proof` | Proved or disproved under declared assumptions? |
| `satisfiability` | SAT/UNSAT under bounds? |
| `runtime_monitor` | Bounded trace satisfy/violate? |
| `evidence_readiness` | Required evidence present and well-formed? |
| `policy_approval` | Configured policy approved/rejected? |

Statuses are kind-scoped (`proved`/`disproved` vs `satisfiable`/`unsatisfiable`
vs `ready`/`not_ready` vs `approved`/`rejected`). There is **no** “stronger
than” ordering among kinds. Adapter wire aliases: `proof` → `theorem_proof`,
`runtime_monitoring` → `runtime_monitor`, `evidence_gate` →
`evidence_readiness`, `policy_decision` → `policy_approval`.

### Attestation kind

How an envelope was produced (for example direct proof verification, verifier
execution, membership, signature, simulation). Kinds are **non-substitutable**;
simulation never upgrades to direct proof on production allow paths.

### Proof corpus

Content-addressed store of `AttestedProofEnvelope@1` records with manifests,
trust policy, coverage policy, and append-only revocation. Producer cache hits
are not authority; **consumer verification under exact roots** is.

### Policy

Configured rules for release, license, security, product admission, or proof
trust (for example `ProofTrustPolicy`, rollout JSON, wallet privacy policy).
**Policy approval** is its own authority kind; it is not theorem proof and not
by itself remote side-effect permission.

### Admissibility

Gate that joins formal intent artifacts, profiles, and evidence into allow /
reject / abstain-style decisions (`logic.admissibility`). Incomplete evidence
**abstains** (fail-closed relative to allow); hard forbid **rejects**.

### Authorization

Side-effect decision under a profile and pinned roots
([GOVERNED_AUTHORIZATION.md](architecture/logic/GOVERNED_AUTHORIZATION.md)).
Composition is deny-overrides and closed-world: absence of a retrieved deny is
**not** an allow. Evaluation is side-effect-free until pre-dispatch enforcement.

### Capability (authorization)

In the **governed authorization** sense: a one-time
`AuthorizationCapability@1` issued with a `DecisionReceipt@1`, atomically
consumed after exact-context pre-dispatch revalidation. Distinct from
**capability** as “feature works on this machine” (see Runtime section).

### Decision receipt

Immutable record of an authorization or admissibility evaluation
(`DecisionReceipt@1`). Records the decision; does not execute tools and does
not prove unrelated claims.

### Pre-dispatch / dispatch

**Pre-dispatch** revalidates roots/context and consumes a one-time capability.
**Dispatch** is control-plane tool invocation (for example MCP
`tools_dispatch`). Dispatch success is not proof or authorization.

### Fail-closed vs graceful degradation

| Mode | When | Effect |
| --- | --- | --- |
| **Fail-closed trust** | Identity integrity, proof, policy admit, authorization, side-effect gates | Missing/indeterminate evidence → non-allow, reject, error—not silent success |
| **Graceful feature degradation** | Optional compute, media, backends, scrapers, non-authoritative helpers | Soft-disable, structured error, or labeled fallback |

Outcome labels such as **UNKNOWN**, **NOT_MODELED**, **unavailable**,
**denied**, and **abstain** answer different questions and must not be
coerced into PROVED or allow
([ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

### Source authority (documentation)

Ranking of which sources win for **documentation claims** (tests/schemas →
implementation → packaging → operator manifests → accepted ADRs → maintained
guides → historical). Separate from `AuthorityKind` on runtime results
([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)).

---

## Runtime, backends, adapters, and capability

### Capability (runtime / product)

Demonstrated ability to perform an operation under current install, extras,
binaries, and configuration. **Discovery** (import/registry) and **availability**
(dep present) are weaker than capability. Empty git submodule directories are
not capability evidence.

### Backend

Concrete implementation selected behind a stable interface: vector stores
(FAISS, Qdrant, Elasticsearch, IPLD), IPFS access (kit, accelerate, HTTP,
Kubo CLI), provers (Z3, CVC5, Lean, …), ZKP engines. Preferred backend ≠ only
backend; missing backend ≠ silent trust success.

### Router / RouterDeps

Process-level selection and caching of backends without hard-wiring optional
stacks at import time (`router_deps`, `ipfs_backend_router`, domain routers).
Callers inject or share `RouterDeps` via `initialize()`.

### Adapter

Thin translation layer that **does not own** core authority:

| Kind | Examples |
| --- | --- |
| Domain IR adapters | `legal_ir`, `security_ir` adapters over `ir_core` |
| Invocation adapters | SkillCenter / prompt / MCP → `InvocationIntentEnvelope` (**non-executing**) |
| Protocol / transport adapters | MCP stdio/HTTP/P2P, graph/UnixFS bridges |
| Backend adapters | Solver or store bindings implementing a protocol |

Adapters must not invent proof or allow by remapping authority kinds.

### Fallback

Documented alternate path when a preferred backend or dependency is missing
(for example Kubo CLI when kit is off; stub embeddings when engines are
absent; `simple_server` when FastAPI stack is unavailable). Fallback
**success** is still a degradation signal for production quality claims.

### Stub

Incomplete or placeholder behavior used for hermetic import, tests, or
degraded runs. Never document a stub path as complete production capability.

### Optional / extra / submodule

| Term | Meaning |
| --- | --- |
| **Optional dependency / extra** | Packaging group in `pyproject.toml` (for example `vectors`, `logic`, `theorem-provers`) |
| **Git submodule** | Separate repository checkout (`.gitmodules`); empty until initialized |
| **Logic submodule registry** | In-package map of logic *families* (`submodule_registry.py`)—**not** the same as git submodules |

### Hermetic import / initialize

Default package import avoids MCP, FastAPI, LLM, and heavy stacks unless env
flags enable them. `initialize()` opt-in wires process-wide router deps
([DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md)).

### MCP (Model Context Protocol)

Tool-host surface (`mcp_server`): stdio/HTTP transports, hierarchical tools,
thin wrappers over domain packages. MCP tools **wrap** domain logic; they do
not own IR identity, proof, or wallet grants.

### Profile G

Risk-aware **planning and evidence** artifacts (Goal / PlanBranch / TaskSpec /
schedule proposals) with CIDs. Planning is **advisory**; execution leases and
side-effect authority remain external and fail closed
([PROFILE_G_PLANNING_AND_EVIDENCE.md](architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md)).

---

## Intermediate representations (IR) and logic families

### IR (Intermediate Representation)

Structured, content-addressed formal artifacts used by logic pipelines—not
“any intermediate object in a data pipeline.” Kernel: `logic.ir_core`. Domain
families share protocols but **not** interchangeable authority.

### IR families (current tree)

| Family | Package | Role |
| --- | --- | --- |
| Kernel | `logic.ir_core` | Canonicalization, identity, provenance, claims, evidence, artifacts, authority protocols |
| Legal IR | `logic.legal_ir` | Legal formalization adapter |
| Security IR | `logic.security_ir` | Immutable security declarations + separate result records |
| Intent IR | `logic.intent_ir` | Source-grounded intent schema; invocation envelopes |

### Formalization / compiler / portfolio

**Formalization** lowers natural or domain views into solver-neutral claims and
obligations. **Compilers** target specific provers. **Portfolio** runs ordered
backends and selects accepted results without rewriting claim identity or
silently changing authority kind.

### External prover

Optional native or library solver (Z3, CVC5, Lean, Coq, CEC/ShadowProver,
ErgoAI, …). Binary discovery ≠ capability; simulation ≠ production proof.

### ZKP

Zero-knowledge proof circuits and backends (`logic.zkp`). Production-oriented
paths bind circuits and verification keys; simulated backends stay labeled and
non-authoritative under strict admissibility profiles.

### UCAN

Capability-oriented authorization tokens used on some integration bridges
(`logic.integration`). Not a substitute for Intent admissibility composition
unless the configured path explicitly consumes them.

---

## Product domains and surfaces (short)

| Term | Meaning |
| --- | --- |
| **Domain package** | Top-level ownership under `ipfs_datasets_py/` (processors, logic, mcp_server, optimizers, knowledge_graphs, vector_stores, wallet, …)—see [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md) |
| **Thin wrapper** | MCP/CLI/facade code that calls a domain and must not reverse import ownership |
| **Facade** | Package-root re-export (for example `profile_g.py`) whose authority remains in the owning domain |
| **Canonical surface** | Preferred path for new work |
| **Compatibility / alias surface** | Supported migration path; not preferred design |
| **GraphRAG** | Graph + retrieval augmented generation paths across knowledge_graphs, processors, optimizers |
| **IPLD** | InterPlanetary Linked Data structures used for content-addressed graphs and some vector/provenance stores |
| **Wallet** | User-controlled trust surface: grants, multisig, privacy policy, wallet operation proofs—not global IR theorem authority |
| **Audit** | Operational audit / provenance integration; monitoring and audit logs are not proof authority |

---

## Optimization and knowledge (domain terms)

These terms remain valid for optimizers and GraphRAG docs; they do not override
authority vocabulary above.

| Term | Meaning in this product |
| --- | --- |
| **Artifact (optimizer)** | Object under iterative improvement (often an ontology dict in GraphRAG optimizers) |
| **Ontology** | Structured entities and relationships extracted for GraphRAG/optimizer loops |
| **Entity / relationship** | Node / edge in an ontology or knowledge graph |
| **Critic score** | Quality score from a critic, usually in \[0.0, 1.0\] with feedback |
| **Optimizer** | Component that improves an artifact from critic or loss feedback |
| **Pipeline / stage / session** | End-to-end workflow; named phase; single optimization run |
| **Extraction** | Turning inputs into entities, relationships, and metadata |
| **Refinement** | Updating the ontology (or artifact) from feedback |
| **Domain (subject)** | Subject area guiding extraction/evaluation (for example `legal`, `medical`)—not the same as package domain ownership |

---

## Canonical aliases and deprecated terminology

### Prefer these canonical names

| Prefer | Instead of / notes |
| --- | --- |
| `logic.integration` | `logic.tools` (**deprecated** compatibility) |
| `AuthorityKind` wire values (`theorem_proof`, …) | Loose prose “proof status” without kind |
| `DecisionReceipt` / `AuthorizationCapability` | Generic “token” for authz consumption |
| `AttestedProofEnvelope` | Undifferentiated “proof blob” |
| Domain packages + thin MCP tools | “Business logic inside mcp_server tools” |
| `ir_core` identity profiles | Branch names, paths, or “latest” as identity |
| Documentation ranks in SOURCE_AUTHORITY | Using completion reports as product truth |
| Git submodule vs logic submodule registry | Using “submodule” without which system |

### AuthorityKind adapter aliases (same wire values)

| Alias seen in adapters | Canonical kind |
| --- | --- |
| `proof` | `theorem_proof` |
| `runtime_monitoring` | `runtime_monitor` |
| `evidence_gate` | `evidence_readiness` |
| `policy_decision` | `policy_approval` |

### Deprecated or non-preferred labels

| Label | Disposition |
| --- | --- |
| `logic.tools` | Deprecated → `logic.integration` |
| “Production ready” from historical phase reports | Rank-7 history only; re-verify against tests/code |
| Generic `status: ok` / `success` across trust layers | Forbidden on trust-bearing codecs; use typed statuses |
| Treating UI visibility, discovery, or green monitors as allow | Explicitly rejected by ADR-003 / SOURCE_AUTHORITY |
| Intent IR schema `intent-ir/v0.1` | Legacy; current marker `intent-ir/v1` |
| setup.py-only console script names without pyproject | Install-path-dependent compatibility; document packaging path used |
| Simulated ZKP / stub embeddings as production quality | Allowed only as labeled degradation, never as theorem or ranking authority |

### Homonyms to disambiguate in prose

| Word | Senses in this repo |
| --- | --- |
| **capability** | (1) runtime feature works; (2) one-time authorization capability object |
| **submodule** | (1) git submodule checkout; (2) logic family in `submodule_registry` |
| **policy** | (1) product/trust rule evaluation; (2) documentation source-authority policy; (3) rollout/ops JSON |
| **receipt** | (1) proof/result receipt; (2) decision receipt; (3) documentation completion receipt; (4) wallet/task receipts—always name the kind |
| **authority** | (1) `AuthorityKind` / result authority; (2) documentation source authority; (3) domain ownership—“who owns this concern” |
| **adapter** | Domain, invocation, transport, or backend adapter—state which |
| **domain** | Package ownership domain vs subject-area domain for optimizers |

---

## Architecture and maintenance sources (cross-links)

| Concern | Canonical source |
| --- | --- |
| Documentation claim ranking; kinds of truth | [SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md) |
| Page lifecycle and audiences | [INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md) |
| System actors and surfaces | [SYSTEM_CONTEXT.md](architecture/SYSTEM_CONTEXT.md) |
| Domain ownership | [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md) |
| End-to-end flows; provenance layers | [END_TO_END_DATA_FLOW.md](architecture/END_TO_END_DATA_FLOW.md) |
| Dependencies, routers, fallbacks | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Git submodules vs external ownership | [INTEGRATION_BOUNDARIES.md](architecture/INTEGRATION_BOUNDARIES.md) |
| IR identity and families | [IR_FAMILY_AND_IDENTITY.md](architecture/logic/IR_FAMILY_AND_IDENTITY.md) |
| Result authority taxonomy | [RESULT_AUTHORITY.md](architecture/logic/RESULT_AUTHORITY.md) |
| Proof corpus and ZKP | [PROOF_ATTESTATION_AND_ZKP.md](architecture/logic/PROOF_ATTESTATION_AND_ZKP.md) |
| Intent authorization and capabilities | [GOVERNED_AUTHORIZATION.md](architecture/logic/GOVERNED_AUTHORIZATION.md) |
| Content identity ADR | [ADR-001](architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |
| Layered authority ADR | [ADR-003](architecture/decisions/ADR-003-LAYERED-AUTHORITY.md) |
| Fail-closed degradation ADR | [ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Profile G planning evidence | [PROFILE_G_PLANNING_AND_EVIDENCE.md](architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md) |

---

## Validation (this page)

```bash
test -s docs/GLOSSARY.md && \
  rg -n 'capability|CID|IR|proof|policy|receipt|provenance|adapter|backend|fallback|authority' docs/GLOSSARY.md
```
