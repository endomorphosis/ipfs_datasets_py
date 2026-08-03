# Logic proof and policy architecture index

| Field | Value |
| --- | --- |
| Interface | `LogicArchitectureIndex@1` |
| Task | `IPFSDOC-045` |
| Status | `canonical` |
| Owner | architecture / logic domain |
| Source of truth | Canonical leaves under `docs/architecture/logic/`; `ipfs_datasets_py/logic/`; `ipfs_datasets_py/logic/submodule_registry.py`; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, operator |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md), [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) |
| Review cadence | after IR identity, compiler/round-trip, prover, constraint, attestation, or authorization surface changes |
| Goal | `IPFSDOC-G060` |

> **Lifecycle:** This page is the **canonical routing hub** for logic, proof,
> and governed policy architecture. It does **not** replace leaf architecture
> guides. Prefer the leaves for contracts, failure modes, and extension detail.
> Completed proposal plans, task boards, session reports, and versioned
> refactor dumps under `docs/logic/` and `docs/architecture/*_PLAN.md` are
> **historical** — useful for migration narrative only, **not** architecture
> authority.

## 1. Purpose

Route developers, agents, security reviewers, and operators to the right logic
proof and policy documentation along **one current route**:

| Need | Go to |
| --- | --- |
| IR ownership, canonical identity, provenance, authority kinds | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) |
| Compilation, decompilation, semantic round trips | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) |
| External provers, hammers, backends, lazy provisioning | [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) |
| Legal/Security constraint compilation and applicability | [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) |
| Proof attestation, corpus verification, ZKP profiles | [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md) |
| Governed intent authorization (evaluate → receipt → pre-dispatch) | [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md) |
| Result-authority taxonomy and non-substitution | [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) |
| Domain ownership of `logic` vs neighbors | [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2 |
| Cross-domain hops (Flow D–E: formalize → prove → authorize → dispatch) | [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) |
| Layered authority / fail-closed trust | [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Maintained operations / rollout runbooks | §7.2 Operations guides |
| Live package component anchors | §5 Component families + §7.3 Component references |
| API, CLI, MCP, tutorials | §7.4 API / tutorials |
| Completed proposal plans (relabeled; not canonical) | §7.5 Historical plans |

**Effects of this index:** one entry point for logic, proof, and policy without
rewriting the leaf guides. New code and docs should link here for orientation,
then drop into the owning leaf.

**Core inequalities (all leaves agree):**

- declaration **CID** ≠ proof ≠ policy decision ≠ authorization **allow** ≠ execution
- SAT/SMT **model** ≠ theorem permission
- simulation / membership attestation ≠ production proof
- proof alone **does not** grant dispatch

## 2. Audience

- **Primary:** developers and agents choosing where to implement or document IR
  families, compilers, provers, constraints, attestations, or authorization.
- **Secondary:** security/policy reviewers checking authority separation;
  operators running IR family, hammer, or legal-gate rollouts; architects
  placing new formalization surfaces relative to MCP, optimizers, and storage.

## 3. Scope and non-goals

### In scope

- Index of **canonical** logic / proof / policy architecture leaves.
- **Ownership** and **current / optional / compat / historical** status per
  logic family (registry-aligned).
- One route across canonical leaves, maintained operations guides, component
  references, API/tutorials, and **relabeled** historical plans.
- Explicit honesty: empty CEC/ErgoAI trees, missing provers, rollout defaults
  off/audit, and simulated ZKP are capability or stage gaps — not architecture
  absence and not production authority.

### Non-goals

- Full IR identity / provenance algorithms → [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md).
- Full compiler / decompiler / parity-policy algorithms → [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md).
- Full prover install recipes and hammer trust contracts → [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md).
- Full Legal/Security hard-filter catalogs → [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md).
- Full attestation-kind algebra and circuit/VK details → [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md).
- Full pre-dispatch consumption mechanics → [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md).
- Full `AuthorityKind` status vocabularies → [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md).
- MCP transport and tool lifecycle framing → [architecture/mcp/](../mcp/).
- GraphRAG optimizer product loops → optimizers package / knowledge track.
- Content-addressed storage backends → [storage/README.md](../storage/README.md).
- Treating completed `*_PLAN.md` proposal documents as current architecture.

## 4. Canonical logic guides

These seven pages are the **architecture authority** for logic, proof, and
policy under `docs/architecture/logic/`. All have status `canonical` as of last
verification (tasks `IPFSDOC-040` … `IPFSDOC-044`).

| Guide | Interface | Owns | Status |
| --- | --- | --- | --- |
| [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) | `IRFamilyArchitecture@1` | Domain-neutral `ir_core` kernel; Legal / Security / Intent family ownership; canonical JSON and CIDs; claims/evidence/provenance; non-interchangeable authority classes | **canonical** — kernel identity for the product |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | `SemanticRoundTripArchitecture@1` | Formal views, compile/decompile, source maps, withhold/abstain/partial, semantic equivalence evaluation without inventing proof | **canonical** — formalization plane |
| [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) | `ExternalProverArchitecture@1` | SAT/SMT/ITP adapters, hammers, portfolio routing, timeouts/UNKNOWN, capability discovery, lazy install; solver results are not theorem permission | **canonical** — prover plane |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) | `ConstraintProofArchitecture@1` | Legal/Security constraint compilation, hard applicability filters, corpus selection, modeled assumptions and coverage gaps | **canonical** — constraint plane |
| [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md) | `ProofAttestationArchitecture@1` | Proof-corpus attestations, non-substitutable attestation kinds, trust policy, revocation, ZKP profiles and VK bindings | **canonical** — attestation plane |
| [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md) | `GovernedAuthorizationArchitecture@1` | Side-effect-free authorization service, portfolio decision, receipts, one-time capabilities, exact-context pre-dispatch consumption | **canonical** — authorization plane |
| [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) | `ResultAuthorityTaxonomy@1` | Closed `AuthorityKind` set, status vocabularies, non-substitution, non-allowing paths; proof ≠ authorization | **canonical** — taxonomy leaf |

```text
                    ┌──────────────────────────────────────┐
                    │  docs/architecture/logic/            │
                    │  README.md  (this index)             │
                    └──────────────────┬───────────────────┘
         ┌───────────┬───────────┬─────┴─────┬───────────┬───────────┐
         ▼           ▼           ▼           ▼           ▼           ▼
 IR_FAMILY_AND_  COMPILERS_AND_  EXTERNAL_  LEGAL_AND_  PROOF_ATTEST  GOVERNED_
 IDENTITY.md     SEMANTIC_       PROVERS.md SECURITY_   ATION_AND_    AUTHORIZATION
 (kernel)        ROUND_TRIP.md   (solvers)  CONSTRAINTS ZKP.md        .md +
                 (views)                    .md         (attest)      RESULT_
                                                                        AUTHORITY.md
```

**Reading order for a new formalization feature:** identity → compilers →
provers → constraints → attestation → result authority → governed
authorization. Skip planes that are out of scope, but do not invent authority
from an earlier plane.

**Kinds of truth (do not collapse):** declaration **CID**, formal **view**
digest, solver **status**, proof **envelope**, attestation **kind**, policy
**decision**, authorization **receipt**, one-time **capability**, MCP
**dispatch observation**. See [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)
and [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md).

## 5. Logic families: ownership and status

**Package owner (product domain):** `ipfs_datasets_py.logic`
([DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2). Machine-readable topology:
`ipfs_datasets_py/logic/submodule_registry.py`
(`logic_submodule_specs()`, `logic_integration_manifest()`, …).

MCP tools under `mcp_server/tools/logic_tools/`, `logic_hammer`, and related
surfaces are **thin wrappers**; algorithms stay in `logic.*` packages.

Status legend:

| Status | Meaning |
| --- | --- |
| **canonical** | Preferred import / design for new work |
| **compat** | Supported transitional surface; prefer canonical when writing new code |
| **optional** | Requires extras, host binaries, secrets, submodules, or rollout stage on |
| **deprecated** | Still importable with warnings or re-exports; do not extend |
| **historical** | Docs or paths describing past plans/migrations; not live architecture |
| **mock / simulation** | Explicit non-production path; green tests ≠ production proof or allow |

### 5.1 Family matrix

| Family | Canonical path(s) | Compat / optional / deprecated | Architecture leaf | Notes |
| --- | --- | --- | --- | --- |
| **IR kernel** | `logic/ir_core/` (canonical, identity, provenance, claims, evidence, protocols, schemas) | Multiformats optional for some CID profiles; IR profile remains hermetic | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) | Domain-neutral inward kernel; dependency-light |
| **Legal IR** | `logic/legal_ir/` | Compatibility adapters; legacy legal parsers elsewhere | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md), [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md), [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Constraint queries + canonical compiler path |
| **Security IR** | `logic/security_ir/` | Migration from legacy security artifacts (ops guide) | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md), [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) | Immutable Security IR; result authority surfaces |
| **Intent IR** | `logic/intent_ir/` (+ `invocation/`) | Non-executing SkillCenter/prompt/MCP adapters | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md), [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md) | Bodies remain data during evaluation |
| **Formalization** | `logic/formalization/` | Domain-neutral samples/views | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Compiler contracts; constraint contracts |
| **FOL / deontic / modal** | `logic/fol/`, `logic/deontic/`, `logic/modal/` | NLP and optional ML paths **optional** | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Conversion is not theorem authority |
| **TDFOL / CEC** | `logic/TDFOL/`, `logic/CEC/` | CEC assets / SPASS / ShadowProver **optional** submodules | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md), [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) | Empty checkout = unprovisioned |
| **Frame-logic** | `logic/flogic/`, `flogic_optimizer.py` | ErgoAI **optional** (`import_check=False` placeholder) | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Crosses optimizers / KG bridges |
| **External provers** | `logic/external_provers/`, `logic/backends/`, `logic/bridge/external_prover_router.py` | Z3/CVC5/Lean/Coq/etc. **optional** + lazy install | [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) | Timeout/UNKNOWN fail closed for trust paths |
| **Hammers** | `logic/hammers/` | Host provers **optional**; MCP/CLI thin | [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) | Hammer output ≠ trusted theorem alone |
| **Proof corpus** | `logic/proof_corpus/` | Simulated ZKP never production-authoritative | [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md), [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) | Trust policy + revocation roots |
| **ZKP** | `logic/zkp/` | `profile-f-zk`, `provekit`, `groth16`, circom/snarkjs **optional** | [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md) | Profile-bound circuit/VK only |
| **Admissibility / authz** | `logic/admissibility/` | Rollout defaults **off/audit**; production stages operator-gated | [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md), [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) | Side-effect-free evaluate; one-time consume |
| **Bridge / integration** | `logic/bridge/`, `logic/integration/`, `logic/integrations/` | `logic.tools` **deprecated** → `logic.integration` | Multiple leaves by concern | Prefer integration over tools |
| **Common / types** | `logic/common/`, `logic/types/` | Shared foundation | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) | Errors, converters, type contracts |
| **Security controls (logic-local)** | `logic/security/`, `logic/security_models/` | Optional rate limits / model IR | Security IR leaves + package docs | Not a second product auth plane |
| **Observability / batch / benchmarks** | `logic/observability/`, `batch_processing.py`, `benchmarks.py`, `monitoring.py` | **optional** | Leaf ops sections | Metrics and harnesses, not authority |
| **MCP / CLI thin surfaces** | `mcp_server/tools/logic_tools/`, hammer tools; `logic/cli.py`, `scripts/cli/logic_cli.py` | Tool availability **optional** by install | §7.4; [mcp/](../mcp/) | No business logic only in tool modules |
| **Registry / package API** | `logic/submodule_registry.py`, `logic/api.py` | Package `__init__` may re-export compat names | This index + [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Prefer `logic.api` / direct submodule imports |

### 5.2 Ownership boundaries (summary)

| Owns (logic / proof / policy) | Does not own |
| --- | --- |
| IR schemas, canonical identity, family adapters | MCP protocol framing and hierarchical tool dispatch |
| Compilers, decompilers, semantic round-trip evaluation | GraphRAG optimizer product loops (`optimizers`) |
| External prover routers, hammers, capability discovery | Hosting Lean/Coq/Z3/CVC5 as a product deliverable |
| Proof corpus, attestation kinds, ZKP profile bindings | Neo4j engine implementation (`knowledge_graphs` — registry cross-list only) |
| Admissibility composition, receipts, pre-dispatch consumption | Wallet grants / UCAN settlement (wallet domain; may consume digests) |
| Result-authority taxonomy and non-substitution | Content storage backends and pin lifecycle (storage domain) |
| Logic submodule registry as machine-readable topology | Treating parse success, SAT, or simulation as allow |

**Inbound:** Python API (`logic.api`), logic CLI, MCP logic/hammer tools,
optimizers and security-verification workflows, SkillCenter / prompt / MCP
invocation adapters (non-executing).

**Outbound:** optional provers and ITPs; optional ErgoAI/CEC assets; optional
ZKP stacks; `knowledge_graphs` bridges for frame-logic graphs; storage helpers
for content-addressed envelopes; MCP dispatch only **after** capability
consumption (authorization does not execute tool bodies).

## 6. Extension recipes (where to implement)

Do **not** put new formalization, prover, or authorization business logic only
in MCP tool modules. Prefer domain packages under `logic/`, then thin wrappers.

| Extension | Recipe summary | Detail |
| --- | --- | --- |
| New IR family or kernel contract | Extend `ir_core` schemas/protocols first; domain adapter points inward only; content-addressed identity | [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) |
| New formal view / compiler | Register under formalization contracts; pin source maps; document withhold/abstain | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) |
| New decompiler or round-trip metric | Source-withheld path; equivalence ≠ proof; version parity policy CIDs | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) |
| New external prover adapter | Capability report + lazy install; map results to correct `AuthorityKind`; timeouts → UNKNOWN | [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) |
| New hammer / premise policy | Trust contract + corpus; never promote portfolio SAT to theorem alone | [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md), `docs/logic/itp_hammer_contract.md` |
| New Legal/Security constraint dimension | Constraint contracts + hard applicability; modeled assumptions explicit | [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) |
| New attestation kind or ZKP profile | Distinct kind; trust policy + VK binding; simulation labeled | [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md) |
| New authorization stage or receipt field | Keep evaluate side-effect-free; pre-dispatch revalidates exact roots; one-time consume | [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md) |
| New result status / authority binding | Closed kind set only; reject substitution helpers | [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) |
| Optional dependency lifecycle | Lazy import; feature degrade OK; inventing proof/allow not OK | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Registry visibility | Add/update `submodule_registry` specs; do not invent a second topology SoT | [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2 |

**Anti-patterns (all leaves agree):** collapsing CID / SAT / proof / policy /
authorization into one “ready” flag; executing skill/prompt/tool bodies during
authorization; silent dual semantics across Legal/Security/Intent; treating
empty submodule or missing prover as undocumented architecture; business logic
only in MCP files; promoting simulation or membership to production theorem;
using completed proposal plans as the live design SoT.

## 7. Documentation routes by authority class

### 7.1 Canonical architecture (preferred)

| Document | Role |
| --- | --- |
| **This index** | Routing, family status, extension map, historical relabeling |
| [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) | Kernel identity and families |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Compile / decompile / equivalence |
| [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) | Provers, hammers, lazy provisioning |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](LEGAL_AND_SECURITY_CONSTRAINTS.md) | Constraints and applicability |
| [PROOF_ATTESTATION_AND_ZKP.md](PROOF_ATTESTATION_AND_ZKP.md) | Attestations and ZKP profiles |
| [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md) | Authorization composition and pre-dispatch |
| [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) | Authority taxonomy and non-substitution |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Product domain map (`logic` §4.2) |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain hops (Flows D–E) |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Content identity vs provenance |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional capability lifecycle |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Non-interchangeable authority layers |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Trust fail-closed vs feature degrade |

### 7.2 Maintained operations guides (operator / rollout)

These are **current operational** guides. Prefer them for rollout stages,
preflight, and day-to-day commands, but treat **architecture contracts** as
owned by the canonical leaves above when they disagree.

| Guide | Use for | Label |
| --- | --- | --- |
| [IR_FAMILY_OPERATIONS.md](../../guides/IR_FAMILY_OPERATIONS.md) | Legal/Security/Intent IR family rollout; advisor stages; roles and fail-closed promotion | **maintained ops** (`IRFamilyRollout@1`) |
| [ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) | Attested authorization operator/developer surface; complements authz leaf | **maintained ops** |
| [logic_intent_legal_gate_rollout.md](../../implementation/runbooks/logic_intent_legal_gate_rollout.md) | LIG rollout runbook, gates, supervisor wiring | **maintained runbook** |
| [THEOREM_PROVER_INTEGRATION_GUIDE.md](../../guides/THEOREM_PROVER_INTEGRATION_GUIDE.md) | End-to-end prover install and pipeline exposition | **maintained guide** — authority still from [EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md) |
| [itp_hammer_user_guide.md](../../logic/itp_hammer_user_guide.md) (+ sibling `itp_hammer_*.md` contracts) | Hammer CLI/MCP, corpus, failure policy, security model | **maintained hammer ops** |
| [LEGAL_DEONTIC_LOGIC_USER_GUIDE.md](../../guides/LEGAL_DEONTIC_LOGIC_USER_GUIDE.md) | Deontic conversion usage narrative | **maintained user guide** |
| [SECURITY_IR_MIGRATION.md](../../security_verification/SECURITY_IR_MIGRATION.md) | Security legacy artifact migration stages | **maintained migration ops** |
| [lazy_theorem_prover_installation.md](../../security_verification/lazy_theorem_prover_installation.md), [optional_solver_installation.md](../../security_verification/optional_solver_installation.md) | Solver provisioning lanes | **ops / optional** |
| [leanstral_legal_ir_rollout.md](../../implementation/runbooks/leanstral_legal_ir_rollout.md) | Leanstral / legal IR rollout | **runbook** |
| [semantic_roundtrip_dynamic_supervisor.md](../../implementation/runbooks/semantic_roundtrip_dynamic_supervisor.md) | Round-trip supervisor operations | **runbook** |
| [semantic_roundtrip_canonical_compiler.md](../semantic_roundtrip_canonical_compiler.md) | Canonical compiler parity policy exposition | **maintained architecture companion** — contracts in [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) |

### 7.3 Component references (implementation anchors)

Use these live package paths as **component references**. Prefer architecture
leaves when contracts conflict with comments or older READMEs.

| Area | Paths |
| --- | --- |
| Kernel | `ipfs_datasets_py/logic/ir_core/` |
| Families | `logic/legal_ir/`, `logic/security_ir/`, `logic/intent_ir/` (+ `invocation/`) |
| Formalization | `logic/formalization/` |
| Conversion families | `logic/fol/`, `logic/deontic/`, `logic/modal/`, `logic/TDFOL/`, `logic/CEC/`, `logic/flogic/` |
| Provers / hammers | `logic/external_provers/`, `logic/hammers/`, `logic/backends/`, `logic/bridge/` |
| Proof / ZKP | `logic/proof_corpus/`, `logic/zkp/` |
| Authorization | `logic/admissibility/` |
| Integration surface | `logic/integration/`, `logic/integrations/`, `logic/api.py`, `logic/cli.py` |
| Registry | `logic/submodule_registry.py` |
| Package-local READMEs | `ipfs_datasets_py/logic/**/README.md` (module notes; not product architecture SoT) |
| Module doc index | [docs/logic/DOCUMENTATION_INDEX.md](../../logic/DOCUMENTATION_INDEX.md) — **component/API index**, subordinate to this architecture hub |

### 7.4 API, MCP, and tutorials

| Surface | Location | Role | Label |
| --- | --- | --- | --- |
| Logic API reference | [docs/logic/logic_API_REFERENCE.md](../../logic/logic_API_REFERENCE.md) | Public import surfaces and high-value APIs | **API reference** — verify against current modules |
| Logic architecture (package-aligned) | [docs/logic/logic_ARCHITECTURE.md](../../logic/logic_ARCHITECTURE.md) | Code-aligned module layout exposition | **maintained component map** — not a substitute for architecture leaves |
| Quickstart / usage | [docs/logic/QUICKSTART.md](../../logic/QUICKSTART.md), [USAGE_EXAMPLES.md](../../logic/USAGE_EXAMPLES.md) | Onboarding examples | **tutorial / examples** |
| Known limitations | [docs/logic/KNOWN_LIMITATIONS.md](../../logic/KNOWN_LIMITATIONS.md) | Current capability gaps | **maintained limitations** |
| TDFOL tutorials | `docs/tdfol/tutorials/` (deontic / modal / temporal) | Logic family tutorials | **tutorial** |
| Security tutorials | [docs/tutorials/security_tutorial.md](../../tutorials/security_tutorial.md), [security_compliance_tutorial.md](../../tutorials/security_compliance_tutorial.md) | Security-facing walkthroughs | **tutorial** — formal gates still from logic leaves |
| MCP logic tools | `ipfs_datasets_py/mcp_server/tools/logic_tools/`, hammer tools | Thin agent-facing tools | **MCP shim** |
| Logic CLI | `ipfs_datasets_py/logic/cli.py`, `scripts/cli/logic_cli.py` | Operator entrypoints (`hammer-*`, …) | **CLI** |
| Dependency / init | [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports, extras (`logic`, `theorem-provers`, ZKP profiles) | **cross-cutting ops** |
| Integration boundaries | [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional provers and submodule ownership | **cross-cutting ops** |

### 7.5 Historical plans (completed proposals — not canonical architecture)

**Relabel rule:** these documents delivered or described work that is now
reflected in code and in the **canonical leaves** above. Keep them for
history, task archaeology, and migration narrative. **Do not** cite them as
the current architecture source of truth. When a leaf and a plan disagree,
**the leaf wins** (after tests/implementation per
[SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

| Document / path | Topic | Label |
| --- | --- | --- |
| [IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md](../IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md) | IR family refactor and Intent IR proposal | **historical plan** (landed) — prefer [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md) |
| [ir_family_refactor_intent_ir.objectives.md](../ir_family_refactor_intent_ir.objectives.md), [ir_family_refactor_intent_ir.todo.md](../ir_family_refactor_intent_ir.todo.md) | IR family taskboard heap | **historical taskboard** |
| [INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md](../INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md) | Attested authorization design proposal | **historical plan** (landed) — prefer [GOVERNED_AUTHORIZATION.md](GOVERNED_AUTHORIZATION.md), [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md) |
| [LOGIC_INTENT_LEGAL_GATE_PLAN.md](../LOGIC_INTENT_LEGAL_GATE_PLAN.md) | Intent · Legal · Security gate proposal | **historical plan** (landed) — prefer constraint + authz leaves |
| [logic_intent_legal_gate.objectives.md](../logic_intent_legal_gate.objectives.md), [logic_intent_legal_gate.todo.md](../logic_intent_legal_gate.todo.md) | LIG goal heap and reviewed task board | **historical taskboard** — ops in §7.2 runbooks |
| `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md` (v2–v22) | Versioned refactor proposal series | **historical plan series** |
| [MASTER_REFACTORING_PLAN_2026.md](../../logic/MASTER_REFACTORING_PLAN_2026.md) | Master refactor umbrella | **historical plan** |
| Other `docs/logic/*_PLAN.md` (parser, NL-UCAN, evergreen, …) | Domain-specific proposals | **historical / plan** unless a later task republishes a leaf |
| `docs/archive/root_status_reports/LOGIC_*`, `ARCHITECTURE_REVIEW_LOGIC_*` | Session completion and improvement summaries | **archive** |
| `docs/logic/archive/**` | Archived stubs and final reports | **archive** |
| Fixed marketing counts and “project complete” slogans in old reports | Inventory snapshots | **historical** — do not use as current inventory authority |

## 8. Decision guide (quick chooser)

```text
What are you doing?
│
├─ Own, name, or identity-pin an IR declaration / family boundary?
│    → IR_FAMILY_AND_IDENTITY.md  (+ ADR-001, ADR-003)
│
├─ Compile, decompile, or measure semantic round-trip?
│    → COMPILERS_AND_SEMANTIC_ROUND_TRIP.md
│    → parity policy / supervisor ops?  §7.2 companions
│
├─ Attach a solver, hammer, backend, or lazy-install path?
│    → EXTERNAL_PROVERS.md
│    → missing binary/extra?  optional deps + THEOREM_PROVER / installer ops
│
├─ Select Legal/Security constraints for an invocation?
│    → LEGAL_AND_SECURITY_CONSTRAINTS.md
│
├─ Attest, verify, revoke, or profile ZKP evidence?
│    → PROOF_ATTESTATION_AND_ZKP.md
│    → simulation only?  not production-authoritative
│
├─ Authorize intent (evaluate, receipt, pre-dispatch consume)?
│    → GOVERNED_AUTHORIZATION.md
│    → rollout stage off/audit?  IR_FAMILY_OPERATIONS + LIG runbook
│
├─ Label a result kind or refuse authority substitution?
│    → RESULT_AUTHORITY.md  (+ ADR-003)
│
├─ Add a new logic capability?
│    → §6 Extension recipes → owning leaf
│
├─ Only reading a completed proposal plan or taskboard?
│    → §7.5 historical, then re-check the matching canonical leaf
│
└─ Cross-domain “where does the artifact go next?”
     → END_TO_END_DATA_FLOW.md, then MCP / storage / optimizers / knowledge
```

## 9. Related architecture and governance

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture documentation hub |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional provers and submodule boundaries |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | CLI/module entry points |
| [processing/README.md](../processing/README.md) | Processing index (may emit text for formalization; does not own IR identity) |
| [storage/README.md](../storage/README.md) | Storage index (CIDs/backends; does not own proof) |
| [mcp/](../mcp/) | MCP server, dispatch, tool lifecycle |
| [knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md](../knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md) | GraphRAG lifecycle (consumes bridges; not formal SoT) |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence precedence |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) | Doc IA |

## 10. Validation

Bounded offline checks for this index:

```bash
# Declared output present and keyword coverage (IPFSDOC-045 gate)
test -s docs/architecture/logic/README.md
rg -n 'IR_FAMILY_AND_IDENTITY|COMPILERS_AND_SEMANTIC_ROUND_TRIP|EXTERNAL_PROVERS|GOVERNED_AUTHORIZATION|RESULT_AUTHORITY' \
  docs/architecture/logic/README.md

# Canonical leaves still present
test -s docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md
test -s docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md
test -s docs/architecture/logic/EXTERNAL_PROVERS.md
test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md
test -s docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md
test -s docs/architecture/logic/GOVERNED_AUTHORIZATION.md
test -s docs/architecture/logic/RESULT_AUTHORITY.md

# Package anchors for major families
test -d ipfs_datasets_py/logic/ir_core
test -d ipfs_datasets_py/logic/legal_ir
test -d ipfs_datasets_py/logic/security_ir
test -d ipfs_datasets_py/logic/intent_ir
test -d ipfs_datasets_py/logic/formalization
test -d ipfs_datasets_py/logic/external_provers
test -d ipfs_datasets_py/logic/hammers
test -d ipfs_datasets_py/logic/proof_corpus
test -d ipfs_datasets_py/logic/zkp
test -d ipfs_datasets_py/logic/admissibility
test -s ipfs_datasets_py/logic/submodule_registry.py
```

Known limits: live SAT/SMT/ITP binaries, ErgoAI/CEC checkouts, ZKP toolchain
extras, and production authorization rollout stages are environment- and
policy-gated. This index only proves **routing, ownership language, and
historical relabeling**, not full prover or authorization runtime proof. A
green simulation, SAT model, or audit-mode decision is not production allow.

## 11. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial **canonical** logic proof and policy architecture index for `IPFSDOC-045` / `LogicArchitectureIndex@1` |
