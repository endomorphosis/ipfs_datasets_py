# ADR-003: Layered authority (non-interchangeable result kinds)

| Field | Value |
| --- | --- |
| Interface | `LayeredAuthorityDecision@1` |
| Task | `IPFSDOC-014` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture; logic/admissibility owners |
| Consulted | documentation-governance; security/policy consumers |
| Source of truth | `ipfs_datasets_py/logic/proof_corpus/model.py` (`AttestedProofEnvelope@1`, `AuthorityKind`, `ProofResultStatus`); `ipfs_datasets_py/logic/admissibility/compose.py` (`AuthorizationDecisionPolicy@1`); `ipfs_datasets_py/logic/admissibility/gate.py`; `ipfs_datasets_py/logic/ir_core/protocols.py` (`AuthorityKind`); MCP hierarchical dispatch (`mcp_server` / `HierarchicalToolManager`); [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) §2 kinds of truth; [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow D–E; [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) §9 |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Cross-cutting product decision; complements package-local MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` without duplicating them |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

IPFS Datasets Python combines dataset pipelines, optional LLM/retrieval paths,
formal logic (IR families, external provers, proof corpus), intent
admissibility, MCP tool dispatch, and operator monitoring. Agents, guides, and
callers routinely collapse distinct pipeline stages into one “result”: a parse
success is treated as a proof; a retrieval hit is treated as a policy grant; a
green monitor dashboard is treated as authorization; a receipt is treated as a
side-effect permit.

Those collapses are unsafe. The product already encodes **typed result
authority** and **closed-world authorization composition** in code:

- Proof envelopes bind a non-hierarchical `result_authority` (for example
  theorem proof vs satisfiability vs runtime monitor vs evidence readiness vs
  policy approval) and a `result_status` that **never upgrades authority by
  itself** (`logic.proof_corpus.model`).
- Attestation kinds are non-substitutable: `simulation` and
  `artifact-membership` cannot become `direct-proof-verification`.
- Authorization composition is deny-overrides and requires positive applicable
  grants / proved non-conflict obligations—not “no deny was retrieved”
  (`AuthorizationDecisionPolicy@1` in `logic.admissibility.compose`).
- Documentation source-authority policy already forbids collapsing discovery,
  capability, syntax, semantics, proof, and authorization
  ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) §2).

This ADR freezes the **layered authority vocabulary** used by logic, MCP,
security, and agent guides so implementers and documentation authors share one
non-interchangeable stack.

## Decision

We will treat the following stages as **distinct authority layers**. No layer
may silently promote its output to the authority of a later layer. Callers,
tools, docs, and agents **must** label which layer produced a claim.

### Decision details

1. **We will maintain a strict authority stack** (earlier layers feed later
   layers; later layers never retroactively rewrite earlier truth kinds):

   | Order | Layer | What it establishes | What it does **not** establish |
   | ---: | --- | --- | --- |
   | 1 | **Parsing** | Input has a structure the grammar/schema accepts | Well-formed meaning under domain rules; truth of content; permission |
   | 2 | **Validation** | Semantic/schema/integrity constraints hold for a declared profile | That a theorem holds; that a side effect is allowed |
   | 3 | **Retrieval / model candidates** | Ranked or generated *candidates* (search hits, LLM drafts, GraphRAG nodes) | Proof, policy admission, or execution rights |
   | 4 | **Satisfiability** | A solver reported SAT/UNSAT (or equivalent) for a modeled finite query under explicit assumptions | Theorem proof under a different authority kind; security of unmodeled real systems; authorization |
   | 5 | **Proof** | A formal property was checked or attested under a declared `result_authority` and attestation kind | Authorization to act; completeness of the real-world system beyond the model |
   | 6 | **Policy** | Release, license, security, or product *policy* evaluated evidence against rules | Theorem authority; automatic remote side effects |
   | 7 | **Authorization** | Side effects (or a specific action class) are **allowed**, **denied**, or **abstained** under a profile | That the action already ran; that monitoring will detect misuse |
   | 8 | **Dispatch** | A tool/API invocation was selected and executed (or rejected by control plane) | That execution was authorized; that results are proofs |
   | 9 | **Monitoring** | Runtime telemetry, health, circuit breakers, or audit signals were observed | Proof of safety properties; authorization; repair of missing evidence |
   | 10 | **Receipts** | An immutable, content-addressed record of what was claimed, decided, or run | By itself, promotion of weak evidence to strong authority |

2. **We must keep result types non-interchangeable.** Renaming fields, sharing
   a generic `status: ok`, or reusing a single boolean across layers is
   forbidden for trust-bearing paths. Prefer typed envelopes (for example
   `ProofResult` / `MonitorResult` / `EvidenceGateResult` / `PolicyDecision` /
   `AdmissibilityDecision` / `AuthorizationAPIResult`) with explicit authority
   tags.

3. **We must preserve hard inequalities** already stated at system level:

   - Discovery ≠ capability ≠ authorization
   - Syntax (parse) ≠ semantics (validation) ≠ proof
   - Model / retrieval output ≠ proof
   - Satisfiability under a model ≠ production security of the unmodeled system
   - Proof ≠ authorization
   - Monitoring ≠ proof
   - UI visibility ≠ execution authority
   - Receipt presence ≠ success of the underlying claim

4. **Promotion is explicit and one-way.** A later layer may *consume* earlier
   artifacts only through documented interfaces (digests, CIDs, profile ids,
   obligation ids). Absence of a deny, empty retrieval, or a green monitor
   **must not** be treated as an allow.

5. **MCP and library surfaces share the same vocabulary.** Hierarchical tool
   discovery and `tools_dispatch` are **dispatch** (and optionally produce
   receipts/traces). They do not invent proof or authorization authority.
   Domain engines remain the home of validation, proof, and policy logic
   (thin-wrapper pattern; package-local MCP ADR-001).

### Why each layer is non-interchangeable (normative rationale)

| Layer | If collapsed into another layer… | Correct consumer of its output |
| --- | --- | --- |
| **Parsing** | Malformed-but-pretty text looks “valid”; agents invent structure | Validators and formalizers only |
| **Validation** | Schema-valid garbage becomes “true” or “proved” | Satisfiability/proof jobs with explicit assumptions; policy with separate evidence |
| **Retrieval / model candidates** | Hallucinations and neighbor docs become law | Human or automated review that creates new reviewed artifacts; never direct proof authority |
| **Satisfiability** | SAT/UNSAT for a toy encoding is sold as end-to-end security | Proof reports scoped to `AuthorityKind.SATISFIABILITY` (or equivalent); release gates that still require modeling coverage |
| **Proof** | Proved formula silently executes tools or mutates production | Admissibility / authorization compose; human release gates |
| **Policy** | “Policy approved” is treated as a theorem | Authorization only when the policy path is an allowed authority path for that action class |
| **Authorization** | “Allowed” is treated as “already done” or as proof | Dispatch and enforcement only |
| **Dispatch** | Tool ran successfully ⇒ safe/legal/proved | Monitoring, receipts, and independent re-checks |
| **Monitoring** | Dashboard green ⇒ property holds forever | Ops response; never theorem upgrade |
| **Receipts** | Artifact exists in store ⇒ claim is true | Auditors and re-validators that recompute digests and re-check authority tags |

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Single unified `Result` / `status: ok` across the stack | Simple APIs; fewer types | Silent authority promotion; untestable boundaries | Rejected — contradicts proof corpus and admissibility design |
| Treat retrieval/LLM as soft proof with confidence scores | Convenient for agents | Confidence is not a proof system; scores are not attestation kinds | Rejected — model output remains candidates only |
| “No deny retrieved” open-world allow | Matches some ACL products | Unsafe for incomplete corpora and partial models | Rejected — closed-world deny-overrides with positive grant obligations |
| Let monitoring or receipts imply authorization | Easy ops story | Telemetry lag and incomplete coverage hide policy gaps | Rejected — monitoring and receipts are non-authorizing evidence classes |
| Do nothing (document only in guides) | Less ADR overhead | Guides outranked by ADRs for *why*; agents re-collapse layers | Rejected — durable vocabulary needs ADR rank |

## Consequences

### Positive

- Logic, MCP, security, and agent documentation share one authority vocabulary.
- Adversarial and release tests can assert non-promotion (status alone never
  upgrades `result_authority`).
- Operators and agents can reason about partial pipelines without inventing
  success.
- Aligns documentation with existing `AttestedProofEnvelope@1` and
  `AuthorizationDecisionPolicy@1` implementations.

### Negative

- Callers must plumb richer types and reason codes instead of a single boolean.
- Agent prompts and UI summaries need extra discipline to avoid collapsing
  layers for brevity.
- Some historical docs and tools still use loose `status` strings; migration is
  incremental and must not silently weaken new paths.

### Neutral / deferred

- Detailed per-domain IR schemas and MCP tool catalogs remain in domain guides
  and package-local MCP docs.
- Exact wire enums may differ by subsystem (`allow|reject|abstain` vs
  `ALLOW|DENY|REVIEW|…`); mapping must preserve fail-closed meaning (see
  [ADR-004](ADR-004-FAIL-CLOSED-DEGRADATION.md)).
- Registries, adapters, and dual-runtime packaging decisions are owned by
  sibling ADRs (IPFSDOC-015 lane), not this record.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. **No silent promotion.** A value produced at layer *N* must not be labeled
   or consumed as layer *N+k* authority without an explicit, tested composition
   step.
2. **Authority kinds are non-hierarchical.** Changing a string label (for
   example renaming simulation to proof) is a contract break, not a upgrade.
3. **Proof does not authorize.** `PROVED` under theorem or satisfiability
   authority never alone becomes `allow` for side effects.
4. **Authorization does not prove.** An allow decision does not rewrite proof
   corpus status or model coverage.
5. **Dispatch does not authorize.** Successful tool execution without a prior
   allow (where required) is a control-plane or product bug, not a new grant.
6. **Monitoring and receipts do not prove or authorize.** They record and
   observe; re-validation remains mandatory for trust claims.
7. **Candidates remain candidates.** Retrieval hits and model drafts require a
   reviewed or formal path before entering proof or policy as *inputs*, never as
   *authorities*.
8. **Positive grants for allow.** Closed-world authorization requires applicable
   positive evidence/grants per policy; absence of deny is insufficient unless a
   *separately accepted* ADR explicitly weakens that rule for a named non-trust
   surface.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

How reviewers and agents check that the codebase and docs still honor this
decision:

```bash
# ADR present and non-empty
test -s docs/architecture/decisions/ADR-003-LAYERED-AUTHORITY.md

# Authority separation still encoded in proof corpus
rg -n 'AuthorityKind|result_authority|NON_AUTHORITATIVE_ATTESTATION|never upgrades authority' \
  ipfs_datasets_py/logic/proof_corpus/model.py

# Authorization compose remains deny-overrides / non-allow paths
rg -n 'AuthorizationDecisionPolicy|deny_overrides|accept_no_retrieved_deny|never become allow' \
  ipfs_datasets_py/logic/admissibility/compose.py

# Docs keep hard inequalities
rg -n 'Proof ≠ authorization|Monitoring ≠ proof|Discovery is not capability' \
  docs/maintenance/SOURCE_AUTHORITY.md docs/architecture/SYSTEM_CONTEXT.md
```

Narrative compliance criteria:

1. New trust-bearing APIs introduce distinct types or tagged unions per layer,
   not a single overloaded success flag.
2. Guides that mention LLM/GraphRAG results state that they are candidates, not
   proofs or authorizations.
3. Security and legal proof reports scope statuses to modeled obligations and do
   not claim unmodeled production systems are secure.
4. MCP dispatch documentation describes control-plane behavior separately from
   domain proof/authz.

## Scope

### Applies to

- Cross-cutting product architecture under `docs/architecture/` and accepted
  decisions under `docs/architecture/decisions/`.
- Logic IR, proof corpus, admissibility, authorization, and security-model
  result reporting.
- MCP hierarchical tools and library facades that surface those results.
- Agent, operator, and security documentation that states what a result *means*.

### Does not apply to

- Purely local developer UX conveniences with **no** trust, release, or side-effect
  claims (still should not lie about capability).
- Package-local MCP implementation ADRs (thin wrapper, dual runtime, etc.)
  except where they must **not contradict** this vocabulary.
- Historical completion reports (rank-7 sources); they remain non-authority.

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-004-FAIL-CLOSED-DEGRADATION.md](ADR-004-FAIL-CLOSED-DEGRADATION.md) | Sister decision: outcome labels and degradation vs fail-closed |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Documentation kinds of truth; authority order |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | System-level hard invariants |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow D (logic→evidence) and Flow E (MCP dispatch) |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Feature degradation vs trust (availability path) |
| `ipfs_datasets_py/logic/proof_corpus/model.py` | `AttestedProofEnvelope@1`, attestation/result authority |
| `ipfs_datasets_py/logic/admissibility/compose.py` | `AuthorizationDecisionPolicy@1` |
| Package MCP ADRs | Thin wrappers and hierarchical dispatch—do not grant proof authority |

## Notes / errata

- Numbering note: objective bundle text once listed fail-closed degradation as
  `ADR-005` and registries as `ADR-004`. The schedulable backlog task
  **IPFSDOC-014** assigns **ADR-003** (this document) and **ADR-004**
  (fail-closed degradation). Later registry/runtime ADRs continue from
  ADR-005 per IPFSDOC-015. Do not renumber without a supersession ADR.
- Wire-level enum spellings differ (`proved` vs `PROVED`, `reject` vs `deny`);
  normative meaning is the layer and fail-closed mapping, not the casing.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted for IPFSDOC-014 (`LayeredAuthorityDecision@1`) |
