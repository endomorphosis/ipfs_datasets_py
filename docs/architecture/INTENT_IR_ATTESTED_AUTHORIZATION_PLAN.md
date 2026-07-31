# Intent IR Attested Authorization and Proof-Corpus Plan

Status: implementation plan
Companion program: `LOGIC_INTENT_LEGAL_GATE_PLAN.md`
Foundation baseline: `IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`
Objective heap: `logic_intent_legal_gate.objectives.md`
Execution board: `logic_intent_legal_gate.todo.md`
Task prefix: `LIG-`

## 1. Executive decision

Extend the completed IR-family foundation with a separate, fail-closed
authorization layer. The layer converts a proposed SkillCenter skill, prompt,
or MCP tool invocation into source-grounded Intent IR, selects applicable
Legal IR and Security IR constraints, verifies cached proof artifacts and
their attestations, asks typed proof backends to discharge the remaining
obligations, and returns a bounded policy decision.

The service evaluates an invocation; it does not execute it. Only an
explicit, current, audience-bound `ALLOW` receipt can be consumed by a later
dispatcher. Retrieval scores, model output, satisfiability, cache hits,
membership proofs, policy configuration, and a drained task board are never
theorem authority.

This plan deliberately reuses the mature Legal IR toolchain rather than
building a second compiler stack. Reuse happens through domain-neutral
contracts and thin adapters. Legal corpus rules, jurisdiction semantics, and
Legal-specific compatibility aliases remain in Legal IR.

## 2. Existing foundation and the remaining gap

The repository already provides most of the difficult leaf capabilities:

- immutable, canonical IR identities, source references, diagnostics,
  evidence, claims, obligations, artifacts, and schema migration;
- pinned and policy-checked SkillCenter ingestion;
- normalized, source-grounded Intent IR and bounded GraphRAG;
- deterministic Intent formalization, proof obligations, decompilation, and
  an advisory learned formalizer;
- Legal IR compilation, pass management, citations, source maps, premise
  ranking and security checks, temporal authority, subgoal decomposition,
  proof routing, reconstruction, semantic diff, and proof-carrying artifacts;
- Security IR declarations, formalization adapters, typed result families,
  and fail-closed portfolio result selection;
- content-addressed caches and IPFS storage helpers; and
- simulated and real-capable ZKP backends, circuit metadata, public-input
  handling, and verification-key support.

Those capabilities do not yet form an authorization system. In particular,
there is no canonical invocation envelope, immutable cross-domain proof
corpus, applicability-first query contract, authority-grade proof-cache key,
cross-domain decision semantics, replay-bound decision receipt, or
pre-dispatch enforcement adapter.

Two existing cache paths are useful migration sources but are not safe as an
authorization authority:

- `logic/common/proof_cache.py` primarily keys theorem/prover inputs and has
  compatibility-oriented TTL/LRU behavior.
- `logic/integration/caching/ipfs_proof_cache.py` stores legacy result-shaped
  JSON without the full policy, corpus, tenant, audience, circuit, key,
  revocation, and applicability bindings required below.

The current Legal ZKP bridge also defaults to a simulated backend. Simulation
is valuable for tests, but the authorization profile must reject it as
cryptographic evidence.

### 2.1 Reconciliation with the active LIG board

The active `logic-intent-legal-gate-v1` board remains the sole implementation
authority. Its LIG-001–021 program supplies or schedules the broad pipeline.
This document appends gap-closing work after those tasks instead of reopening
the completed IRF foundation or competing with in-flight LIG leaves.

| Existing LIG work | Preserved outcome | Gap closed by this extension |
|---|---|---|
| LIG-005/LIG-006 source adapters and fixtures | Prompt/MCP/skill content becomes grounded Intent IR without execution. | A proposed invocation also needs actor, delegation, audience, arguments, concrete effects, environment, nonce, policy/corpus roots, and redaction commitments. |
| LIG-007–013 family caches, proof store, query, and attestation | Artifacts are content addressed, queryable, and optionally attested. | Authorization needs immutable corpus manifests, complete authority-grade cache identity, tenant/scope filters, temporal/revocation roots, exact circuit/VK/public-input semantics, independent verification, and legacy quarantine. |
| LIG-014–016 profiles, gate, and end-to-end fixture | The public gate returns allow/reject/abstain with structured reasons. | `ALLOW` must require explicit applicable permission, proved non-conflict, hard Security invariants, discharged obligations, coverage, and exact-context evidence; decisions need a consumer-verifiable receipt. |
| LIG-017/LIG-018 supervisor and MCP bridges | Supervisor/MCP callers can normalize, formalize, query, and check. | Evaluation must remain separate from dispatch; a dispatcher needs audience/request binding, one-time consumption, fresh revocation/environment checks, and TOCTOU protection. |
| LIG-019/LIG-020 benchmark and runbook | Offline evaluation and shadow/canary guidance exist. | Release needs adversarial, metamorphic, tenant/privacy, cache-substitution, circuit/VK, replay/race, chaos, redacted telemetry, promotion, and rollback evidence. |

## 3. Scope

### 3.1 In scope

- Proposed invocations originating from:
  - a pinned SkillCenter skill;
  - a user or agent prompt; or
  - an MCP server tool call.
- Intent normalization and deterministic multiview formalization.
- Retrieval and verification of cached Legal, Security, and Intent proof
  artifacts.
- Legal applicability by jurisdiction, authority, effective time,
  supersession, exception, and subject/resource scope.
- Security applicability by principal, capability, trust zone, asset,
  requested effect, data class, and runtime context.
- Typed proof obligations and cross-domain policy composition.
- `ALLOW`, `DENY`, `REVIEW`, `INDETERMINATE`, and `ERROR` outcomes.
- A narrowly scoped, expiring receipt/capability for a downstream dispatcher.
- Offline fixtures, audit/shadow rollout, and later bounded enforcement.

### 3.2 Out of scope

- Executing a skill, prompt, or tool call.
- Claiming that generated formal logic is correct because an LLM emitted it.
- Treating similarity or GraphRAG retrieval as legal applicability.
- Treating a ZKP as evidence of any proposition not encoded by its reviewed
  circuit and public-input contract.
- Providing legal advice or replacing jurisdiction-specific human review.
- Inferring permission from the absence of a retrieved prohibition.
- Silently translating between incompatible logic families.
- Replacing the existing Legal or Security public APIs during this program.

## 4. Safety and authority invariants

1. **Source grounding is mandatory.** Every semantic term and selected
   constraint traces to immutable sources or is marked as an explicit,
   policy-approved assumption.
2. **Declarations and runs are distinct.** An IR declaration, backend result,
   runtime observation, evidence gate, policy decision, and ZK attestation
   have non-interchangeable types.
3. **Retrieval is never proof.** Lexical, graph, dense, and learned ranks can
   order candidates only after hard scope filters.
4. **Models are advisory only.** Model-generated candidates pass the same
   schema, grounding, bounded-repair, deterministic compilation, and proof
   checks as any other candidate.
5. **A cache hit is never self-authenticating.** The consumer independently
   verifies canonical identities, manifests, proof objects, public inputs,
   circuits, verification keys, freshness, revocation, and policy bindings.
6. **Simulation cannot authorize.** Simulated ZKP or solver-success fixtures
   may exercise tests, but cannot satisfy an enforcement trust profile.
7. **Unknown is not allow.** Missing evidence, unsupported semantics,
   incompatible logic, timeout, backend unavailability, ambiguity, stale
   policy, stale proof, and incomplete corpus coverage cannot produce
   `ALLOW`.
8. **SAT is not permission.** Satisfiability means only that a model exists
   for a particular encoding. Authorization requires the configured grant,
   non-conflict, safety, and obligation proofs.
9. **Decisions are context bound.** Actor, tenant, audience, nonce, tool
   version, argument commitment, resources, policy root, corpus roots,
   environment snapshot, effective time, and expiry are part of the receipt.
10. **Dispatch revalidates.** The dispatcher verifies the receipt immediately
    before the side effect and consumes one-time authorization atomically.

## 5. Target architecture

```text
SkillCenter skill        prompt             MCP invocation
       |                    |                      |
       +--------- source-specific adapters -------+
                            |
                 InvocationIntentEnvelope@1
                            |
                 Intent IR normalization
                            |
          deterministic multiview formalization
                            |
                AuthorizationQueryBundle@1
                            |
       +--------------------+--------------------+
       |                    |                    |
 Legal applicability   Security scope      Intent/proof
 and constraints       and constraints     artifact query
       |                    |                    |
       +------ hard-filtered proof-corpus query-+
                            |
           manifest / proof / ZK verification
                            |
               selected evidence pack
                            |
         per-view proof and contradiction jobs
                            |
            fail-closed decision policy
                            |
       AuthorizationDecision + DecisionReceipt
                            |
             optional pre-dispatch verifier
```

The architecture keeps three boundaries explicit:

- source adapters decide how an invocation is observed and normalized;
- domain adapters decide how Legal, Security, and Intent semantics become
  typed claims and applicability evidence; and
- the authorization policy decides how verified results combine. It does not
  rewrite a policy decision into a theorem.

## 6. Canonical contracts

All contracts use exact schema IDs, canonical UTF-8 serialization, immutable
or defensively copied fields, domain-separated digests, bounded collection
sizes, and explicit unknown-version rejection.

### 6.1 `InvocationIntentEnvelope@1`

Required identity and scope fields:

- envelope schema/version and invocation kind;
- tenant, actor, delegator chain, subject attributes, and trust domain;
- intended audience/dispatcher and deployment/environment identity;
- source reference: SkillCenter record and pinned revision, prompt digest, or
  MCP server/tool/version/schema identity;
- tool argument commitment and a separately handled redacted display view;
- requested actions, effects, capabilities, assets, resources, data classes,
  network destinations, filesystem scopes, subprocess needs, and secrets
  references;
- preconditions, expected postconditions, failure behavior, rollback
  behavior, and verification steps;
- jurisdiction, location, purpose, consent/legal-basis claims, and effective
  evaluation time when supplied;
- sandbox and runtime facts supplied by an attested environment observer;
- policy profile, corpus snapshot requirements, nonce, creation time,
  deadline, and trace ID; and
- source maps, diagnostics, explicit assumptions, and unsupported fields.

Raw secrets, authentication tokens, unrestricted prompt bodies, and private
tool arguments are not corpus metadata. Store redacted views and
domain-separated commitments; retrieve secret values only at dispatch time
through an authorized secret provider.

Source adapters:

- `SkillCenterInvocationAdapter` consumes a validated `SkillRecord` and
  `IntentIRDocument`; skill text remains hostile data and is never executed.
- `PromptInvocationAdapter` separates the user's requested outcome from
  quoted/tool-produced content and records ambiguity instead of inventing
  capabilities.
- `MCPInvocationAdapter` binds server identity, tool schema digest, argument
  commitment, advertised annotations, transport peer, and resolved runtime
  capabilities. Tool annotations are claims, not trusted facts.

### 6.2 `ConstraintArtifact@1`

A domain adapter emits one or more solver-neutral constraint artifacts:

- domain and logic-family identifiers;
- source and corpus snapshot identities;
- typed vocabulary/symbol table;
- premises, claims, grants, prohibitions, obligations, exceptions,
  invariants, and assumptions;
- applicability predicates and a declared closed/open-world policy;
- formal views plus source maps and loss/unsupported diagnostics;
- compiler, adapter, ontology, policy, and configuration identities; and
- deterministic artifact and obligation digests.

Existing `FormalizationArtifact` and `ProofObligation` contracts should be
composed or extended through versioned adapters, not forked.

### 6.3 `AttestedProofEnvelope@1`

The authority-grade proof record binds:

- envelope schema, proof-artifact CID, canonical statement digest,
  assumption digest, and obligation digest;
- domain, logic family, proof/result authority, and status;
- source snapshot, corpus manifest/root, policy, ontology, adapter, compiler,
  translation, solver, and reconstruction identities;
- proof bytes or proof-object CID plus checked proof metadata;
- ZK attestation kind, circuit ID/version/digest, verification-key
  ID/version/digest, public inputs, proof-system/backend ID, and security
  profile;
- effective/expiry interval, jurisdiction, tenant/scope, subject/resource
  selectors, and evidence coverage;
- build manifest, parent artifacts, source maps, diagnostics, and producer;
- supersession and revocation references; and
- optional signatures or trusted-execution receipts, kept distinct from
  theorem proof.

The `attestation_kind` is mandatory:

- `direct-proof-verification`: the reviewed circuit verifies the underlying
  formal proof and binds all public inputs;
- `verifier-execution`: the attestation proves or vouches for a particular
  verifier execution under an explicitly trusted mechanism;
- `artifact-membership`: the attestation proves membership or possession
  only; or
- `simulation`: non-authoritative test evidence.

Policy must not treat membership, possession, a signature, or simulation as
direct theorem verification.

### 6.4 `ProofCorpusManifest@1`

Each corpus release is immutable and append-only:

- corpus domain, namespace, schema, snapshot/root CID, parent root, build
  time, producer, and approved policy;
- ordered entries containing envelope CID and hard-filter metadata;
- source set, compiler/solver/circuit/VK registries, revocation snapshot, and
  trusted root identities;
- deterministic index manifests and index-builder identity;
- licensing, retention, privacy, jurisdiction, and tenant policy;
- completeness/coverage declaration and known gaps; and
- integrity and promotion receipts.

Bodies live in a content-addressed store. Rebuildable lexical, graph, range,
and dense indices are separate artifacts bound to the manifest root. There is
no mutable unqualified `latest` alias in an authorization request.

### 6.5 `AuthorizationQueryBundle@1`

The query bundle contains:

- invocation envelope and Intent IR/formalization identities;
- exact evaluation context and approved policy profile;
- required Legal, Security, and Intent corpus roots;
- typed grant, deny, obligation, safety, and applicability subgoals;
- required evidence coverage and tolerated logic/backend capabilities;
- resource/time/attempt limits; and
- diagnostic and trace policy.

Each formal view stays in its native supported logic. Cross-view policy
combines typed results; it does not concatenate modal, Datalog, temporal,
Hoare, and SMT strings into an unsound formula.

### 6.6 `AuthorizationDecision@1` and `DecisionReceipt@1`

Internal outcomes:

- `ALLOW`: every mandatory evidence, applicability, permission,
  non-conflict, safety, and obligation gate passes under an approved profile;
- `DENY`: an applicable prohibition, failed hard Security invariant,
  revoked authority, explicit policy deny, or verified counterexample applies;
- `REVIEW`: evidence is valid but policy requires human/legal/security
  approval or there is resolvable ambiguity;
- `INDETERMINATE`: coverage, semantics, proof, backend, or applicability is
  insufficient; and
- `ERROR`: malformed input or internal integrity failure.

At an enforcement boundary, only a valid `ALLOW` maps to execution
eligibility. Every other status rejects the dispatch.

The existing LIG `AdmissibilityStatus@1` wire contract remains compatible:
`ALLOW` maps to `allow`, `DENY` maps to `reject`, and `REVIEW`,
`INDETERMINATE`, and `ERROR` map to `abstain` with typed reason/detail fields.
The richer internal status must not be inferred back from a legacy
`abstain` without its bound receipt.

The receipt binds the full request digest, selected evidence pack, all proof
attempts, decision policy, result authorities, corpus and revocation roots,
environment facts, actor, audience, nonce, issued/expiry times, allowed
effects, and residual obligations. A capability token derived from it must be
attenuated, audience restricted, short lived, and one time.

## 7. Reusing the Legal IR toolchain

| Existing Legal IR capability | Reuse approach | Boundary to preserve |
|---|---|---|
| `legal_ir_compiler_api` and canonical compiler | Adapt its request/result, diagnostics, source-map, and build-manifest patterns behind shared compiler protocols. | Legal syntax, aliases, and corpus validation stay Legal-owned. |
| `legal_ir_pass_manager` | Extract a domain-neutral immutable pass/result protocol and generic dependency scheduler. | Do not move or rewrite legacy passes in the extraction task. |
| citations, diagnostics, source maps, schema evolution | Reuse canonical data patterns and migration receipts. | An Intent adapter may not fabricate Legal citations. |
| premise selection and `legal_ir_premise_security` | Reuse bounded ranking, provenance checks, taint/quarantine, and selection receipts after hard applicability filters. | Ranking never establishes relevance, applicability, or truth. |
| temporal authority | Reuse effective windows, change graphs, supersession, and diagnostics. | Add jurisdiction/authority adapters rather than pretending time alone determines applicability. |
| obligations and subgoals | Reuse decomposition and stable obligation identity. | Preserve domain-specific modality and explicit unsupported cases. |
| proof router, hammer, translations, backend conformance | Reuse typed attempts, capability probes, translations, reconstruction, and portfolio receipts. | A successful translation or SAT result is not proof of permission. |
| proof-carrying artifacts and build manifests | Generalize the consumer-verifiable envelope and fail-closed validation policy. | Keep a compatibility reader for existing Legal artifacts. |
| semantic diff and decompiler | Reuse round-trip and semantic-mutation tests for review. | Review renderings have no authority. |
| learned guidance and proof feedback | Reuse candidate ranking and bounded feedback interfaces. | Learned output remains advisory and cannot weaken assumptions, sources, or policy. |

The extraction rule is “new shared leaf, existing domain adapter.” Initial
tasks must not perform a mass move of the Legal package or change its public
identities. Differential tests compare the legacy Legal path with the adapter
path before any consolidation.

## 8. Query and applicability pipeline

### 8.1 Hard filters before ranking

Candidate proof entries are rejected before BM25, graph, vector, or learned
ranking when any mandatory field is incompatible:

- tenant/visibility or data-retention boundary;
- corpus root or approved parent lineage;
- jurisdiction, authority level, subject, actor, purpose, resource, action,
  capability, or data class;
- effective/expiry time;
- supersession/revocation state;
- policy, ontology, schema, adapter, compiler, circuit, VK, backend, or
  security-profile allowlist;
- logic-family/backend capability; or
- proof/result authority required by the query.

Approximate retrieval may then rank the bounded surviving set. The response
records candidates considered, filters applied, omissions, score features,
selected premises, and coverage gaps.

### 8.2 Independent verification

The query consumer:

1. resolves the exact corpus and revocation roots;
2. verifies manifest and entry canonical identities;
3. fetches bounded proof bodies by CID;
4. verifies proof-to-statement, assumption, source, compiler, solver,
   circuit, VK, and public-input bindings;
5. rejects unknown algorithms, downgrade attempts, simulations, invalid
   signatures, expired items, revoked items, and unverifiable parents;
6. runs the approved native proof verifier or approved ZK verifier locally;
7. checks applicability evidence and corpus coverage; and
8. emits an immutable `SelectedEvidencePack`.

Network fetching and verification are separable so unit tests are fully
offline and enforcement can use a prewarmed, pinned snapshot.

### 8.3 Legal applicability

The Legal adapter must represent rather than guess:

- jurisdiction and territorial/subject-matter scope;
- authority hierarchy and precedential weight;
- enactment/effective/repeal windows;
- supersession, amendments, exceptions, definitions, and cross-references;
- actor/subject, resource, purpose, consent, and threshold predicates;
- competing or contradictory authorities; and
- human-review requirements and known corpus gaps.

Failure to prove applicability is not permission. Contradictory applicable
authorities yield `REVIEW` or `INDETERMINATE` unless a reviewed,
jurisdiction-specific conflict rule resolves them.

### 8.4 Security applicability

The Security adapter selects declarations and verified result artifacts by:

- principal/delegation/capability;
- trust zone, asset, data class, channel, and network/filesystem scope;
- action, state transition, requested effect, failure/rollback behavior;
- environment and sandbox evidence;
- threat model and policy version; and
- proof, monitor, evidence-gate, and policy-result authority.

A runtime monitor observation may satisfy a policy gate but cannot substitute
for a theorem proof. Conversely, a theorem over an abstract model does not
prove that the live deployment matches that model without separate
environment evidence.

## 9. Decision semantics

For each requested action/effect, the composer produces at least:

- an applicability obligation for every selected authority;
- an explicit permission/grant obligation when policy requires positive
  authorization;
- an applicable-prohibition/counterexample check;
- Security invariants and capability/least-privilege checks;
- Legal and policy obligations that must hold before, during, or after use;
- consistency and translation/reconstruction obligations; and
- corpus/evidence coverage obligations.

An illustrative closed-policy profile allows only when:

```text
verified_evidence
and applicability_complete
and applicable_grant_proved
and prohibition_query_proved_non_conflicting
and all_hard_security_invariants_proved
and all_pre_dispatch_obligations_discharged
and no_revocation_or_expiry
and decision_context_exactly_bound
```

“Proved non-conflicting” means a reviewed backend has discharged the declared
non-conflict obligation under explicit bounded semantics. It does not mean
that a text search found no prohibition.

Deny-overrides is the default combining policy. A verified explicit deny or
hard-safety violation produces `DENY`; valid but policy-mandated escalation
produces `REVIEW`; all proof gaps and unknowns produce `INDETERMINATE`.
Profiles may be stricter but cannot silently weaken the authority invariants.

Portfolio behavior follows Security result-policy practice:

- backend capability and logic support are explicit;
- attempts, timeouts, translations, assumptions, and reconstruction are
  recorded;
- result selection is deterministic and order independent;
- contradictory authoritative backend results fail closed and page review;
- unavailable backends never become successful attempts; and
- policy decisions retain links to typed proof results without adopting their
  authority kind.

## 10. Proof corpus, cache, and ZK attestation

### 10.1 Storage layout

Use a new `logic/proof_corpus` package for authority-grade artifacts:

- immutable envelope and manifest codec;
- content-addressed body store protocol with local and IPFS adapters;
- deterministic hard-filter and ranking indices;
- revocation/supersession snapshot;
- query/audit receipts; and
- legacy migration readers.

Do not mutate the legacy `ProofCache` key or silently reinterpret old records.
The migration reader labels missing bindings and admits a legacy record only
to non-authoritative/audit profiles until it is rebuilt and re-attested.

### 10.2 Cache identity

Proof-object cache identity includes statement, assumptions, obligation,
logic, domain, source/corpus, compiler, translation, solver, reconstruction,
circuit, VK, proof policy, and tenant/scope bindings.

Decision-cache identity additionally includes the complete invocation,
arguments, actor/delegation, audience, purpose, environment, effective time,
policy, corpus roots, revocation root, and evidence-coverage profile.

Positive decisions are short lived and never reused across tenant, actor,
audience, tool version, argument commitment, policy root, corpus root, or
environment snapshot. Negative/unknown results are not reused across changed
contexts unless the profile explicitly proves monotonicity. Cache keys never
contain plaintext secrets.

### 10.3 ZK trust policy

A ZKP demonstrates only the constraints encoded by a particular circuit over
its bound public inputs. Therefore:

- circuit source/review identity and semantic specification are versioned;
- trusted setup, VK rotation, and compromise/revocation are explicit;
- public inputs bind statement, assumptions, proof/corpus roots, verifier
  policy, circuit/VK, and any privacy-preserving subject/context commitments;
- underconstrained circuits and mismatched public inputs are adversarial test
  cases;
- fallback from a real backend to simulation is a hard authorization failure;
- artifact-membership proofs do not become theorem proofs;
- witness material is minimized, zeroized where possible, excluded from
  logs, and governed by tenant/privacy policy; and
- a non-ZK native proof may still qualify when the selected policy permits it
  and its verifier/result bindings are complete.

## 11. API and enforcement surface

Primary Python service:

```python
decision = IntentAuthorizationService.evaluate(
    invocation=envelope,
    policy_ref=policy_ref,
    legal_corpus_ref=legal_root,
    security_corpus_ref=security_root,
    intent_corpus_ref=intent_root,
    environment=environment_snapshot,
    budget=authorization_budget,
)
```

Supporting interfaces:

- `normalize_skill_invocation(...)`
- `normalize_prompt_invocation(...)`
- `normalize_mcp_invocation(...)`
- `query_proof_corpus(...)`
- `verify_attested_proof(...)`
- `compose_authorization_query(...)`
- `verify_decision_receipt(...)`
- `consume_dispatch_capability(...)`

The CLI accepts files/CIDs and emits a redacted JSON decision plus a
machine-readable exit status. It defaults to audit/offline mode and never
dispatches a command.

Pre-invocation integration is a small adapter around a dispatcher:

1. create and evaluate the envelope;
2. reject unless the decision is `ALLOW`;
3. just before dispatch, validate audience, nonce, expiry, request digest,
   policy/corpus/revocation roots, and live environment binding;
4. atomically mark the one-time capability consumed; and
5. emit a completion/side-effect observation separate from the authorization
   receipt.

## 12. Threat model and required controls

| Threat | Required control |
|---|---|
| Prompt or SkillCenter corpus injection | Treat source as hostile data, never execute during ingestion, use pinned revisions, grounding and quarantine policy. |
| Malicious MCP schema/annotation | Bind server/tool/schema identities; annotations are untrusted claims; resolve actual host capabilities independently. |
| Wrong/stale jurisdiction or law | Hard applicability filters, effective-time graph, exact corpus root, coverage gaps, supersession/revocation check, review fallback. |
| Contradictory authority | Preserve both authorities, run conflict policy, never rank one away silently, fail to review/indeterminate. |
| Cache substitution or cross-tenant leak | Domain-separated complete cache keys, tenant/visibility filtering before fetch, independent CID/manifest/proof verification. |
| Replayed decision | Audience/request digest, nonce, short expiry, one-time atomic consumption, fresh environment and revocation validation. |
| Confused deputy | Actor/delegation and audience binding, least-privilege allowed effects, no caller-controlled dispatcher identity. |
| Policy/corpus/VK downgrade | Exact approved identities, minimum security profile, signed/pinned registry roots, reject implicit latest/fallback. |
| Simulated or forged ZKP | Reject simulation for authority, verify backend/proof system, circuit, VK, public inputs, and proof locally. |
| Underconstrained circuit | Reviewed semantic spec, negative witnesses, mutation tests, differential native verification, circuit/VK promotion gate. |
| Proof/witness or argument leakage | Redacted views, commitments, field-level retention policy, bounded diagnostics, no secrets in cache keys/logs. |
| TOCTOU between decision and action | Revalidate at dispatch, bind live environment, consume once atomically, minimize TTL. |
| Resource-exhaustion proof query | Bounded candidate count, bytes, graph depth, solver time/memory, backend attempts, and deterministic cancellation. |
| Unsound cross-logic translation | Typed view boundaries, translation receipts, reconstruction, explicit unsupported status, differential tests. |

## 13. Observability and privacy

Metrics use bounded labels and never include raw prompts, arguments, witness
data, secrets, formulas with private constants, or unbounded CIDs as labels.
Record:

- counts and latency by source kind, outcome, policy profile, and proof
  authority;
- candidate/filter/verification counts and cache hit classes;
- stale/revoked/tampered/unsupported/simulation rejection counts;
- backend availability, timeout, disagreement, and reconstruction failures;
- review and false-allow/false-deny adjudication rates; and
- receipt consumption, replay, expiry, and TOCTOU rejection counts.

Every decision has a redacted replay bundle containing exact immutable
identities and deterministic local fixtures where licensing/privacy permits.
Audit retention and erasure policy distinguish content-addressed public legal
sources from tenant-private invocation material.

## 14. Validation strategy

### 14.1 Unit contracts

- canonical identity and mutation-after-construction;
- schema/version/unknown-field policy;
- all three invocation adapters and adversarial source payloads;
- manifest, index, CID, parent, revocation, and supersession integrity;
- native and ZK proof verification, circuit/VK mismatch, simulation rejection;
- cache isolation and complete-key mutations;
- temporal/jurisdiction/actor/resource applicability;
- result-authority non-substitution;
- decision truth table and deny/review/unknown precedence;
- receipt expiry, audience, nonce, request mutation, and one-time consumption.

### 14.2 Golden and metamorphic corpus

Include synthetic, reviewable cases for:

- explicitly allowed, explicitly denied, conditional, exception, ambiguous,
  conflicting, expired, superseded, revoked, and missing-law scenarios;
- capability granted/denied, trust-zone mismatch, data egress, filesystem,
  network, subprocess, destructive effect, and rollback requirements;
- skill, prompt, and MCP representations of the same intent;
- semantically relevant mutations to actor, action, arguments, resource,
  purpose, jurisdiction, time, tool version, and environment;
- poisoned ranking neighbors and partition-isolation attacks; and
- valid/invalid native proofs and real/simulated/malformed ZK attestations.

Metamorphic tests require relevant mutations to change obligations or
invalidate a receipt, while irrelevant display/trace changes do not perturb
the declaration identity defined by policy.

### 14.3 Integration and differential checks

- pinned offline SkillCenter record to Intent IR to decision;
- prompt and MCP equivalents to the same obligation bundle;
- old Legal compiler/proof artifact versus new adapter result;
- Security portfolio result selection through the new query;
- local content store versus IPFS-backed store with identical manifest root;
- native proof verification versus qualifying direct ZK verification;
- deterministic rebuild and replay under frozen roots; and
- backend disagreement, timeout, revocation change, corrupt index, partial
  network, and dispatcher race/consumption tests.

Unit and integration suites require no live network, paid model, or installed
optional solver. Scheduled capability jobs report unavailable coverage
explicitly and must never convert skips into authority.

## 15. Delivery waves and parallelism

Tasks continue the active four-shard LIG board. Predicted files are disjoint
within each declared parallel set, and `Allow concurrent with` is used only
for reviewed, file-exclusive peers. Existing LIG tasks remain prerequisites
and are not rewritten while their supervisors are live.

| Wave | Tasks | Outcome |
|---|---|---|
| Existing | LIG-001–021 | Complete or deliver the shared formalization, source adapters, family caches, base proof corpus/gate, bridges, benchmark, and runbook. |
| A | LIG-022–023 | Freeze the canonical invocation and cross-domain applicability contracts. |
| B | LIG-024–028 | Build three invocation adapters and Legal/Security applicability selectors in file-exclusive lanes. |
| C | LIG-029 | Freeze the authority-grade attested-proof and trust policy after the base corpus/attestation leaves. |
| D | LIG-030–032 | Add immutable manifests/revocation, hard-filtered audit query, and independent native/ZK/legacy verification in parallel. |
| E | LIG-033 | Compose explicit permission, non-conflict, safety, obligation, and coverage proof jobs with deterministic portfolio policy. |
| F | LIG-034, LIG-039, LIG-040 | Add receipts, telemetry/rollout controls, and adversarial fixtures in separate files. |
| G | LIG-035 | Integrate the side-effect-free exact-context authorization service. |
| H | LIG-036–038 | Add pre-dispatch runtime enforcement and harden supervisor/MCP/API consumers in parallel. |
| I | LIG-041 | Single-owner exports, conformance, runbook, release evidence, and rollback gate. |

No early task edits shared package exports or `logic/submodule_registry.py`.
LIG-041 is the sole owner of final datasets export/registry integration.

## 16. Rollout and governance

1. **Off:** schemas, fixtures, and verification code land without invocation.
2. **Audit:** explicit offline evaluations produce decisions that no
   dispatcher consumes.
3. **Shadow:** sampled real invocation envelopes are evaluated with redacted
   data; legacy behavior remains authoritative.
4. **Deny-only canary:** only verified hard denies can block a tightly scoped
   test population; unknown/review paths page humans and false-deny budgets
   are measured.
5. **Bounded allow-token canary:** a reviewed dispatcher accepts short-lived,
   one-time receipts for an allowlisted, reversible, low-risk action set.
6. **Enforce:** expand only after current policy/corpus/circuit/VK promotion
   receipts and adversarial gates pass.

Human approval is mandatory for:

- supported jurisdictions and conflict rules;
- legal/security corpus promotion and declared coverage;
- authority and evidence-combination policy;
- circuit/VK/trusted-setup promotion and rotation;
- retention/privacy policy and tenant sharing;
- allow-token action/effect scope and dispatcher audience; and
- canary expansion or rollback.

Rollback disables receipt consumption first, preserves redacted evidence, and
returns the system to audit/shadow. It never marks old receipts valid under a
new policy or corpus root.

## 17. Goals and ownership

The existing LIG-G000–G080 goals remain the broad delivery hierarchy. Four
continuation goals make the missing authority and enforcement contracts
explicit:

- `LIG-G090`: canonical invocation boundary and Legal/Security applicability;
- `LIG-G100`: authority-grade proof corpus, revocation, and verification;
- `LIG-G110`: exact-context authorization decisions, receipts, and runtime
  enforcement; and
- `LIG-G120`: adversarial conformance, governance, rollout, and release.

The objective heap is durable intent. The todo board is an execution
projection. A completed task is not proof that a goal is complete; only fresh,
current-tree evidence satisfying each objective's evidence-source policy can
promote it.

## 18. Definition of done

The program is done only when:

- all three source kinds deterministically produce canonical, source-grounded
  invocation envelopes and Intent formalizations;
- Legal and Security adapters reuse reviewed compiler/proof patterns without
  changing legacy public behavior;
- an exact immutable proof-corpus snapshot can be queried offline, every
  selected proof and attestation is independently verified, and stale,
  revoked, simulated, tampered, under-bound, or cross-tenant entries fail
  closed;
- `ALLOW` requires explicit applicable permission, non-conflict, hard-safety,
  obligation, coverage, and context-binding evidence;
- every other internal result rejects at the enforcement boundary;
- receipts are audience/request/policy/corpus/environment/nonce/expiry bound
  and one-time consumption survives race tests;
- golden, adversarial, metamorphic, differential, chaos, and deterministic
  replay suites pass with zero authority-boundary violations;
- legacy caches are read only through a non-authoritative migration path
  until rebuilt;
- simulated ZKP evidence cannot reach `ALLOW`;
- observability reveals gaps and disagreements without leaking sensitive
  content; and
- the reviewed rollout/runbook and rollback drill have fresh evidence tied to
  the exact repository tree, policies, corpus roots, circuits, and keys.
