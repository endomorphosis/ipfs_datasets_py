# Logic Intent · Legal · Security Gate Objective Heap

This objective heap is the durable source of intent for the LIG program:
reuse LegalIR formalization tooling for IntentIR, cache and ZKP-attest
Legal/Security/Intent formal artifacts, query that corpus, and admit or reject
intentions (skills, prompts, MCP tools) under Legal+Security constraints.

Companion files:

- Plan: [`LOGIC_INTENT_LEGAL_GATE_PLAN.md`](./LOGIC_INTENT_LEGAL_GATE_PLAN.md)
- Deep authorization design: [`INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`](./INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md)
- Todo board: [`logic_intent_legal_gate.todo.md`](./logic_intent_legal_gate.todo.md)
  (**sole active** implementation board; IRF board absorbed)
- Predecessor: [`IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`](./IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md)
  / [`ir_family_refactor_intent_ir.todo.md`](./ir_family_refactor_intent_ir.todo.md)
  (IRF **37/37 completed** — do not re-run or co-launch)

### Unified board merge (no duplication / contention / locks)

| Concern | Rule |
|---------|------|
| Duplication | IRF-delivered formalization spine, Intent formalizer, Legal measured path, and Security formalization adapter are **foundation** (LIG-002/004/010 completed; LIG-003 residual CID hygiene only). Net-new work starts at prompt/MCP adapters, proof caches, proof_corpus, admissibility, supervisor/MCP. |
| Contention | Single board namespace `logic-intent-legal-gate-v1`. Do **not** run `ir-family-v1` implementation supervisors while this board is active. |
| Locks / state | Isolated state + worktree roots under `data/agent_supervisor/logic_intent_legal_gate/` (and optional XDG `…/agent-supervisor/logic-intent-legal-gate-v1/`). Never share with IRF/ASREF. |
| Gaps | Base delivery is LIG-001–021; authority, applicability, receipt, enforcement, privacy, and adversarial continuation is LIG-022–041. |

Program invariants:

- Work lands on branch `feature/logic-intent-legal-gate` (datasets) until cutover;
  accelerate-side wiring may use a matching branch only for LIG-G070.
- IntentIR never executes skill/prompt/MCP text; GraphRAG/LLM/advisor never
  become theorem proof authority.
- Proof, monitor, evidence-gate, policy, and ZKP-verify authorities remain
  non-substitutable (`ir_core.protocols.AuthorityKind`).
- Fail closed: missing attestation, integrity failure, unsupported semantics,
  or incomplete constraints → abstain or reject, never silent allow.
- `allow` additionally requires an applicable positive grant, proved
  non-conflict, hard Security invariants, discharged obligations, declared
  corpus coverage, freshness/revocation checks, and exact invocation context.
- Retrieval, SAT, cache presence, signature, artifact membership, policy
  declaration, runtime observation, and simulated ZKP never substitute for the
  specific proof authority required by an enforcement profile.
- Parallel lanes honor `Bundle:` / `Outputs:` ownership; shared registries and
  package `__init__.py` files change only in designated integration tasks.
- Goals close only with current-tree validation evidence, not todo status alone.

## LIG-G000 Intent admissibility under Legal and Security with attested proof corpus

- Status: active
- Parent:
- Fib priority: 1
- Track: logic-platform
- Priority: P0
- Bundle: lig/root
- Parallel lane: lig-integration
- Resource class: cpu-validation
- Goal: Deliver a fail-closed pipeline that normalizes SkillCenter skills, prompts, and MCP tool invocations into IntentIR and formal obligations using shared Legal formalization tooling; cache and ZKP-attest Intent, Legal, and Security formal artifacts; query that corpus by CID and source identity; and decide allow, reject, or abstain for each intent against Legal and Security constraints under explicit profiles.
- Evidence: LIG-G010, LIG-G020, LIG-G030, LIG-G040, LIG-G050, LIG-G060, LIG-G070, LIG-G080, LIG-G090, LIG-G100, LIG-G110, LIG-G120
- Evidence criteria: all child goals have fresh current-tree validation; composite gate fixtures cover explicit allow, legal-reject, security-reject, contradiction, review/abstain, and incomplete evidence; required native/ZKP proof verifies under exact circuit/VK/public-input and revocation policy; invocation, receipt, tenant, audience, nonce, expiry, environment, and one-time dispatch checks pass; supervisor/MCP entry points load without heavy prover import side effects.
- Evidence source policy: A root receipt must enumerate every child goal terminal receipt, bind repository tree digests and policy/profile versions, and report zero authority-boundary or execution violations. Model narrative and task-board drainage alone do not qualify.
- Outputs: docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md, docs/architecture/INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md, docs/architecture/logic_intent_legal_gate.objectives.md, docs/architecture/logic_intent_legal_gate.todo.md, tests/integration/logic/test_intent_admissibility_gate.py, tests/integration/logic/test_attested_intent_authorization.py
- Predicted files: tests/integration/logic/test_intent_admissibility_gate.py, tests/integration/logic/test_attested_intent_authorization.py, ipfs_datasets_py/logic
- Interfaces: IntentAdmissibilityGate@1, ProofCorpusQuery@1, IntentAuthorizationService@1, DecisionReceipt@1
- Validation: python -m pytest tests/integration/logic/test_intent_admissibility_gate.py tests/integration/logic/test_attested_intent_authorization.py -q
- Acceptance: Offline fixtures prove end-to-end lineage from Intent source to an exact-context gate decision with applicable Legal and Security proof CIDs; allow requires positive permission, non-conflict, Security invariants, obligations, coverage, freshness, revocation, and authority checks; simulated ZKP cannot authorize production; no source instructions execute; every non-allow status rejects dispatch; public Python/MCP APIs preserve allow/reject/abstain compatibility.
- Gap task: Close the highest-priority incomplete child without weakening fail-closed or authority boundaries.
- Refinement: Wave shared formalization first; parallelize Intent formalization with Legal and Security proof caches; then store, gate, integrate, and evaluate.
- Embedding query: IntentIR LegalIR SecurityIR SkillCenter formalization ZKP proof corpus admissibility gate MCP agent supervisor
- AST query: IntentIRDocument CanonicalCompiler ProofCorpusStore AdmissibilityGate ZKPVerifier

## LIG-G010 Shared formalization spine and Legal toolchain extraction

- Status: active
- Parent: LIG-G000
- Fib priority: 1
- Track: formalization
- Priority: P0
- Bundle: lig/formalization-shared
- Parallel lane: lig-formal-shared
- Resource class: cpu-medium
- Goal: Stabilize domain-neutral formalization protocols and extract Legal’s measured compile, decompile, and semantic round-trip contracts so Intent and Security adapters implement the same interfaces without importing Legal corpus rules.
- Evidence: ipfs_datasets_py/logic/formalization, ipfs_datasets_py/logic/legal_ir/canonical_contracts.py, ipfs_datasets_py/logic/ir_core/protocols.py, LIG-002 completed, LIG-003 residual
- Evidence criteria: shared protocols have golden tests; Legal adapter remains a pure implementation of shared protocols; Intent/Security can import protocols without legal_ir side effects; no authority promotion from advisor or GraphRAG.
- Evidence source policy: Fresh unit receipts for formalization and legal_ir canonical contracts qualify. Moving files without protocol tests does not.
- Outputs: ipfs_datasets_py/logic/formalization/compiler.py, ipfs_datasets_py/logic/legal_ir/canonical_contracts.py, tests/unit/logic/formalization/test_contracts.py
- Predicted files: ipfs_datasets_py/logic/formalization, ipfs_datasets_py/logic/legal_ir, tests/unit/logic/formalization
- Interfaces: FormalizationCompiler@1, FormalizationDecompiler@1, FormalizationRoundTrip@1, SharedFormalizationProtocol@1
- Validation: python -m pytest tests/unit/logic/formalization/test_contracts.py tests/unit/logic/legal_ir/test_canonical_compiler.py tests/unit/logic/legal_ir/test_canonical_decompiler.py tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py tests/unit/logic/legal_ir/test_formalization_adapter.py -q
- Acceptance: Protocols live under formalization or ir_core without domain imports; Legal measured compiler/decompiler/round-trip bind configuration and CIDs; Intent package can depend on protocols only; semantic mutation tests still fail closed.
- Gap task: Close LIG-003 frozen benchmark adapter L1 CID hygiene only; do not re-extract shared protocols (IRF-delivered).
- Refinement: Do not rewrite large Legal autoencoder paths; keep aliases; only extract shared contracts. Protocol surface is `formalization.compiler.FormalizationCompiler` (no separate protocols.py required).
- Embedding query: shared formalization protocol Legal canonical compiler decompile round trip Intent adapter
- AST query: FormalizationCompiler CanonicalCompiler CanonicalDecompiler CanonicalRoundTrip ProofObligation

## LIG-G020 Intent formalization production path from skills prompts and MCP

- Status: active
- Parent: LIG-G010
- Fib priority: 2
- Track: intent
- Priority: P0
- Bundle: lig/intent-compile
- Parallel lane: lig-intent
- Resource class: cpu-proof-type-check
- Goal: Complete a production Intent formalization path that normalizes SkillCenter skills, free-form prompts, and MCP tool invocations into IntentIR and lowers them through shared formalization protocols into typed views and solver-neutral obligations with full source grounding.
- Evidence: ipfs_datasets_py/logic/intent_ir/formalize, ipfs_datasets_py/logic/intent_ir/source_adapters, ipfs_datasets_py/logic/intent_ir/normalize, LIG-004 completed
- Evidence criteria: offline pilot fixtures compile deterministically; unsupported semantics surface as diagnostics; GraphRAG premises are assumptions only; prompt and MCP adapters fail closed on hostile content; no skill_md execution.
- Evidence source policy: Fresh unit and offline pipeline receipts bound to pinned fixture CIDs qualify. Live SkillCenter network access is optional and separately recorded.
- Outputs: ipfs_datasets_py/logic/intent_ir/formalize/compiler.py, ipfs_datasets_py/logic/intent_ir/formalize/obligations.py, ipfs_datasets_py/logic/intent_ir/source_adapters/prompt.py, ipfs_datasets_py/logic/intent_ir/source_adapters/mcp_tool.py, tests/unit/logic/intent_ir/formalize, tests/fixtures/intent_ir/admissibility
- Predicted files: ipfs_datasets_py/logic/intent_ir, tests/unit/logic/intent_ir, tests/fixtures/intent_ir
- Interfaces: IntentFormalizer@1, PromptIntentAdapter@1, MCPToolIntentAdapter@1, IntentObligationSet@1
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize tests/unit/logic/intent_ir/source_adapters -q
- Acceptance: Skill, prompt, and MCP fixtures each produce IntentIRDocument + formal artifact CIDs; obligation digests are stable under canonicalization; advisor patches cannot change modality or provenance; decompile/round-trip policy matches shared FormalizationRoundTrip.
- Gap task: LIG-005 prompt/MCP adapters + LIG-006 gate fixtures (formalizer protocol path already IRF-delivered via LIG-004).
- Refinement: Parallelize skill path vs prompt/MCP adapters after schema stability; reuse Legal view registry patterns.
- Embedding query: IntentIR SkillCenter prompt MCP tool formalize obligations source grounded fail closed
- AST query: IntentFormalizer IntentIRDocument IntentAction ProofObligation MCPToolIntentAdapter

## LIG-G030 Legal proof corpus cache and ZKP attestation

- Status: active
- Parent: LIG-G010
- Fib priority: 2
- Track: legal-proof
- Priority: P0
- Bundle: lig/legal-proof-cache
- Parallel lane: lig-legal-cache
- Resource class: cpu-proof-translate
- Goal: Persist Legal formal artifacts, theorem results, and ZKP attestations for corpus fragments so constraints are loadable by CID without re-running full formalization or provers when integrity holds.
- Evidence: ipfs_datasets_py/logic/legal_ir, ipfs_datasets_py/logic/zkp, ipfs_datasets_py/logic/zkp/legal_theorem_semantics.py
- Evidence criteria: cache hits rehash envelopes and fail closed on drift; ZKP prove/verify path works for the pinned legal-theorem circuit fragment or explicitly abstains; no cache hit returns proof authority without a theorem result receipt.
- Evidence source policy: Fresh legal cache and ZKP unit receipts over offline fixtures qualify. Simulated backends must be labeled and never counted as production ZKP success under zkp-required profiles.
- Outputs: ipfs_datasets_py/logic/legal_ir/proof_cache.py, ipfs_datasets_py/logic/zkp/statements/legal_constraint.py, tests/unit/logic/legal_ir/test_proof_cache.py, tests/unit/logic/zkp/test_legal_constraint_attestation.py
- Predicted files: ipfs_datasets_py/logic/legal_ir, ipfs_datasets_py/logic/zkp, tests/unit/logic/legal_ir, tests/unit/logic/zkp
- Interfaces: LegalProofCache@1, LegalConstraintZKP@1
- Validation: python -m pytest tests/unit/logic/legal_ir/test_proof_cache.py tests/unit/logic/zkp/test_legal_constraint_attestation.py -q
- Acceptance: Put/get by CID; integrity rehash; optional ZKP attach/verify; index by jurisdiction/profile/source digest; CLI or library entry documents offline rebuild.
- Gap task: Add cache schema + one golden attested legal fixture.
- Refinement: Keep ZKP circuit definition separate from cache index; reuse provekit artifacts where possible.
- Embedding query: LegalIR proof cache ZKP attestation CID integrity constraint theorem receipt
- AST query: LegalProofCache ZKPProver ZKPVerifier legal_theorem_semantics ProofReceipt

## LIG-G040 Security proof and constraint cache with attestation

- Status: active
- Parent: LIG-G010
- Fib priority: 2
- Track: security-proof
- Priority: P0
- Bundle: lig/security-proof-cache
- Parallel lane: lig-security-cache
- Resource class: cpu-proof-translate
- Goal: Cache SecurityIR-derived formal constraints, policy decisions, and optional ZKP attestations so the gate can load security constraints by CID and profile without re-adapting legacy models each call.
- Evidence: ipfs_datasets_py/logic/security_ir, ipfs_datasets_py/logic/security_ir/results.py
- Evidence criteria: declaration identity immutable under cache; verification/policy results retain AuthorityKind; golden exchange/Xaman fixtures cache and reload with integrity checks.
- Evidence source policy: Fresh security_ir unit and cache receipts qualify. Legacy import alone without integrity map does not.
- Outputs: ipfs_datasets_py/logic/security_ir/constraint_cache.py, ipfs_datasets_py/logic/security_ir/formalization_adapter.py, tests/unit/logic/security_ir/test_constraint_cache.py
- Predicted files: ipfs_datasets_py/logic/security_ir, tests/unit/logic/security_ir
- Interfaces: SecurityConstraintCache@1, SecurityFormalizationAdapter@1
- Validation: python -m pytest tests/unit/logic/security_ir/test_constraint_cache.py tests/unit/logic/security_ir -q
- Acceptance: Constraints addressable by CID; profile filters; fail closed on unknown extensions; optional ZKP attach reuses shared zkp statement helpers.
- Gap task: Cache one exchange and one Xaman constraint set with integrity tests.
- Refinement: Do not break Security public freeze contracts from IRF-G010.
- Embedding query: SecurityIR constraint cache policy decision proof receipt CID profile
- AST query: SecurityConstraintCache SecurityIR FormalizationAdapter PolicyDecision

## LIG-G050 Unified proof corpus store and query API

- Status: active
- Parent: LIG-G020, LIG-G030, LIG-G040
- Fib priority: 3
- Track: proof-store
- Priority: P0
- Bundle: lig/proof-store
- Parallel lane: lig-store
- Resource class: io-artifact
- Goal: Provide a family-agnostic content-addressed proof corpus store and query API over Intent, Legal, and Security formal artifacts, receipts, and ZKP attestations with integrity-bound indexes.
- Evidence: ipfs_datasets_py/logic/proof_corpus
- Evidence criteria: put/get/query operations re-verify digests; queries by source, obligation, family, and profile are deterministic; concurrent writers do not corrupt indexes; load never executes embedded code.
- Evidence source policy: Fresh unit and property tests with offline multi-family fixtures qualify. IPFS network presence is optional.
- Outputs: ipfs_datasets_py/logic/proof_corpus/store.py, ipfs_datasets_py/logic/proof_corpus/query.py, ipfs_datasets_py/logic/proof_corpus/index.py, ipfs_datasets_py/logic/proof_corpus/schemas.py, tests/unit/logic/proof_corpus
- Predicted files: ipfs_datasets_py/logic/proof_corpus, tests/unit/logic/proof_corpus
- Interfaces: ProofCorpusStore@1, ProofCorpusQuery@1
- Validation: python -m pytest tests/unit/logic/proof_corpus -q
- Acceptance: API supports get_by_cid, list_by_source, list_constraints_for_obligation, verify_attestation; schemas versioned; CLI smoke optional.
- Gap task: Implement store + query for three offline fixtures (one per family).
- Refinement: Index is rebuildable from envelopes; envelopes remain authoritative.
- Embedding query: proof corpus store query CID Intent Legal Security ZKP attestation index
- AST query: ProofCorpusStore ProofCorpusQuery ArtifactEnvelope AttestationRecord

## LIG-G060 Composite Intent admissibility gate

- Status: active
- Parent: LIG-G050
- Fib priority: 3
- Track: gate
- Priority: P0
- Bundle: lig/admissibility-gate
- Parallel lane: lig-gate
- Resource class: cpu-validation
- Goal: Implement a fail-closed admissibility gate that, given Intent formal obligations and a constraint profile, queries attested Legal and Security constraints and returns allow, reject, or abstain with structured reasons and bound artifact CIDs.
- Evidence: ipfs_datasets_py/logic/admissibility, tests/integration/logic/test_intent_admissibility_gate.py
- Evidence criteria: fixtures cover allow, legal-hard-reject, security-hard-reject, contradiction, missing-evidence abstain, and zkp-required missing-proof abstain; decisions are deterministic for a fixed corpus snapshot.
- Evidence source policy: Fresh integration receipt over versioned fixtures qualifies. Heuristic similarity or model judgment does not.
- Outputs: ipfs_datasets_py/logic/admissibility/gate.py, ipfs_datasets_py/logic/admissibility/profiles.py, ipfs_datasets_py/logic/admissibility/reasons.py, tests/integration/logic/test_intent_admissibility_gate.py, tests/fixtures/logic/admissibility
- Predicted files: ipfs_datasets_py/logic/admissibility, tests/integration/logic, tests/fixtures/logic
- Interfaces: IntentAdmissibilityGate@1, AdmissibilityProfile@1, AdmissibilityDecision@1
- Validation: python -m pytest tests/integration/logic/test_intent_admissibility_gate.py tests/unit/logic/admissibility -q
- Acceptance: Decision object includes status, reasons, intent_cid, constraint_cids, attestation_results, profile_id, config_digest; default profile never allows without constraints; zkp-required profile verifies proofs.
- Gap task: Land gate core + four golden decisions.
- Refinement: Keep join logic free of SkillCenter I/O; accept pre-built Intent formal CIDs.
- Embedding query: admissibility gate allow reject abstain Intent Legal Security ZKP profile fail closed
- AST query: AdmissibilityGate AdmissibilityDecision AdmissibilityProfile ProofCorpusQuery

## LIG-G070 Agent supervisor and MCP integration

- Status: active
- Parent: LIG-G060
- Fib priority: 5
- Track: integration
- Priority: P1
- Bundle: lig/supervisor-integration
- Parallel lane: lig-supervisor
- Resource class: cpu-medium
- Goal: Wire the proof corpus and admissibility gate into ipfs_accelerate_py agent supervisor IR registry, constraint adapters, and MCP tools so runtime intent checks use the same fail-closed contracts.
- Evidence: ipfs_accelerate_py/agent_supervisor/ir_registry.py, ipfs_accelerate_py/agent_supervisor/ir_adapters.py, ipfs_accelerate_py/agent_supervisor/intent_constraint_adapter.py
- Evidence criteria: registry discovers LIG schemas; adapters load pinned artifacts; MCP tools normalize/formalize/query/check without executing tools; import of agent_supervisor remains free of optional heavy provers.
- Evidence source policy: Fresh accelerate unit/integration receipts and datasets gate fixtures qualify. Cross-repo docs alone do not.
- Outputs: ipfs_accelerate_py/agent_supervisor/ir_registry.py, ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py, ipfs_datasets_py/mcp_server tools or docs for LIG tools, tests under both repos as listed per task
- Predicted files: ipfs_accelerate_py/agent_supervisor, ipfs_datasets_py/mcp_server, test/api
- Interfaces: SupervisorAdmissibilityBridge@1, MCPIntentAdmissibility@1
- Validation: python -m pytest test/api/test_agent_supervisor_intent_admissibility.py -q
- Acceptance: Documented env/flags; pinned artifact load path; decision-runtime can observe gate results; MCP tool schemas published.
- Gap task: Bridge module + one MCP tool + one supervisor test.
- Refinement: Prefer thin bridge in accelerate calling datasets APIs; avoid duplicating gate logic.
- Embedding query: agent supervisor IR registry MCP intent admissibility bridge constraint adapter
- AST query: IRRegistry IntentIRAdapter AdmissibilityGate MCP

## LIG-G080 Evaluation benchmarks and controlled rollout

- Status: active
- Parent: LIG-G060, LIG-G070
- Fib priority: 5
- Track: quality
- Priority: P1
- Bundle: lig/eval-rollout
- Parallel lane: lig-eval
- Resource class: cpu-validation
- Goal: Provide reproducible benchmarks, leakage guards, shadow/canary rollout runbooks, and operator documentation for the LIG pipeline.
- Evidence: tests/benchmarks/logic, docs/implementation/runbooks
- Evidence criteria: held-out sources never train the gate; rebuild is deterministic; shadow default; canary requires zero authority violations.
- Evidence source policy: Fresh benchmark receipt + reviewed runbook qualify.
- Outputs: tests/benchmarks/logic/test_intent_admissibility_benchmark.py, docs/implementation/runbooks/logic_intent_legal_gate_rollout.md, docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md
- Predicted files: tests/benchmarks/logic, docs/implementation/runbooks, docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md
- Interfaces: IntentAdmissibilityBenchmark@1
- Validation: python -m pytest tests/benchmarks/logic/test_intent_admissibility_benchmark.py -q
- Acceptance: Benchmark documents splits, corpus snapshot CID, profiles, and metrics; runbook includes rollback; plan updated with measured outcomes.
- Gap task: Add minimal benchmark fixture and rollout runbook skeleton.
- Refinement: No production default flip without canary receipt.
- Embedding query: benchmark shadow canary rollout Intent admissibility Legal Security
- AST query: BenchmarkReceipt RolloutRunbook

## LIG-G090 Canonical invocation boundary and cross-domain applicability

- Status: active
- Parent: LIG-G010, LIG-G020
- Fib priority: 3
- Track: authorization-platform
- Priority: P0
- Bundle: lig/authorization-contracts
- Parallel lane: lig-auth-contracts
- Resource class: cpu-proof-type-check
- Goal: Bind each proposed SkillCenter, prompt, or MCP invocation to actor, delegation, audience, concrete tool arguments/effects, resources, environment, time, policy and corpus roots, then select applicable Legal and Security constraints through shared source-grounded contracts.
- Evidence: LIG-022, LIG-023, LIG-024, LIG-025, LIG-026, LIG-027, LIG-028
- Evidence criteria: canonical/mutation/redaction tests cover all security-relevant invocation fields and source kinds; Legal applicability changes under jurisdiction/authority/time/exception/subject/resource mutations; Security applicability changes under principal/delegation/capability/trust-zone/asset/effect/data/environment mutations; unsupported or ambiguous semantics remain explicit and cannot allow.
- Evidence source policy: Fresh offline canonical-byte, adapter, differential Legal/Security, source-map, applicability, and semantic-mutation receipts qualify. Source annotations, model output, similarity rank, a mutable revision, or an inferred capability without an attested source do not.
- Outputs: ipfs_datasets_py/logic/intent_ir/invocation/model.py, ipfs_datasets_py/logic/intent_ir/invocation/skillcenter.py, ipfs_datasets_py/logic/intent_ir/invocation/prompt.py, ipfs_datasets_py/logic/intent_ir/invocation/mcp.py, ipfs_datasets_py/logic/formalization/constraint_contracts.py, ipfs_datasets_py/logic/legal_ir/constraint_query.py, ipfs_datasets_py/logic/security_ir/constraint_query.py
- Predicted files: ipfs_datasets_py/logic/intent_ir/invocation, ipfs_datasets_py/logic/formalization/constraint_contracts.py, ipfs_datasets_py/logic/legal_ir/constraint_query.py, ipfs_datasets_py/logic/security_ir/constraint_query.py
- Interfaces: InvocationIntentEnvelope@1, ConstraintArtifact@1, LegalConstraintQuery@1, SecurityConstraintQuery@1
- Validation: python -m pytest tests/unit/logic/intent_ir/invocation tests/unit/logic/formalization/test_constraint_contracts.py tests/unit/logic/legal_ir/test_constraint_query.py tests/unit/logic/security_ir/test_constraint_query.py -q
- Acceptance: Envelopes are immutable, canonical, source-grounded, redaction-aware, and contain no raw secrets; source adapters never execute content or call a tool; domain constraints retain native logic and authority; hard applicability filters precede ranking; unresolved applicability, conflict, coverage, or unsupported semantics fails to abstain/reject.
- Gap task: Close the smallest missing envelope, source adapter, constraint, or applicability field with an adversarial semantic-mutation fixture.
- Refinement: Keep the envelope, each source adapter, shared constraint contract, Legal selector, and Security selector in exclusive files; do not rewrite completed source adapters or legacy domain compilers.
- Embedding query: invocation intent actor delegation audience arguments effects resources environment jurisdiction Legal Security applicability source grounding
- AST query: InvocationIntentEnvelope ConstraintArtifact LegalConstraintQuery SecurityConstraintQuery

## LIG-G100 Authority-grade proof corpus, revocation, and independent verification

- Status: active
- Parent: LIG-G030, LIG-G040, LIG-G050
- Fib priority: 5
- Track: proof-security
- Priority: P0
- Bundle: lig/proof-authority
- Parallel lane: lig-proof-authority
- Resource class: cpu-proof-verify
- Goal: Harden the base proof corpus into immutable exact-root snapshots whose Legal, Security, and Intent proof artifacts, native proofs, and ZK attestations are independently verified under complete policy, tenant, scope, time, revocation, circuit, verification-key, and public-input bindings.
- Evidence: LIG-029, LIG-030, LIG-031, LIG-032
- Evidence criteria: a deterministic offline corpus rebuild has the same manifest root and query trace; hard filters execute before ranking; tamper, stale/expired, superseded/revoked, wrong-tenant/scope/root/policy/compiler/solver/circuit/VK/public-input, downgrade, simulation, partial-fetch, cache-substitution, and legacy-incomplete fixtures all fail closed; selected evidence has a consumer-verified receipt.
- Evidence source policy: Fresh manifest/revocation, hard-filter query/audit, native proof verification, qualifying real-ZK capability, legacy migration, tamper and selected-evidence receipts qualify. A CID, cache hit, signature, producer status, membership proof, simulated proof, or optional test skip alone does not.
- Outputs: ipfs_datasets_py/logic/proof_corpus/model.py, ipfs_datasets_py/logic/proof_corpus/policy.py, ipfs_datasets_py/logic/proof_corpus/manifest.py, ipfs_datasets_py/logic/proof_corpus/revocation.py, ipfs_datasets_py/logic/proof_corpus/applicability.py, ipfs_datasets_py/logic/proof_corpus/audit.py, ipfs_datasets_py/logic/proof_corpus/verifier.py, ipfs_datasets_py/logic/proof_corpus/migration.py
- Predicted files: ipfs_datasets_py/logic/proof_corpus/model.py, ipfs_datasets_py/logic/proof_corpus/policy.py, ipfs_datasets_py/logic/proof_corpus/manifest.py, ipfs_datasets_py/logic/proof_corpus/revocation.py, ipfs_datasets_py/logic/proof_corpus/applicability.py, ipfs_datasets_py/logic/proof_corpus/audit.py, ipfs_datasets_py/logic/proof_corpus/verifier.py, ipfs_datasets_py/logic/proof_corpus/migration.py
- Interfaces: AttestedProofEnvelope@1, ProofTrustPolicy@1, ProofCorpusManifest@1, SelectedEvidencePack@1
- Validation: python -m pytest tests/unit/logic/proof_corpus -q
- Acceptance: Corpus snapshots are append-only and exact-root addressed; bodies and indices are separately manifest-bound; every proof identity includes statement/assumptions/obligation/source/compiler/solver/reconstruction/circuit/VK/policy/scope; every decision query pins corpus and revocation roots; simulated and incomplete legacy evidence is non-authoritative; ZKP authority never exceeds reviewed circuit semantics.
- Gap task: Close the smallest missing envelope, manifest, revocation, applicability, audit, verifier, or migration binding with a deterministic tamper fixture.
- Refinement: Build on LIG-011–013 in new file-exclusive leaves; do not silently reinterpret or mutate legacy family caches; keep network fetching separable from offline verification.
- Embedding query: attested proof corpus manifest CID Merkle revocation tenant applicability ZKP circuit verification key public inputs legacy migration
- AST query: AttestedProofEnvelope ProofTrustPolicy ProofCorpusManifest AttestedProofVerifier SelectedEvidencePack

## LIG-G110 Exact-context authorization decisions, receipts, and enforcement

- Status: active
- Parent: LIG-G060, LIG-G070, LIG-G090, LIG-G100
- Fib priority: 5
- Track: authorization-runtime
- Priority: P0
- Bundle: lig/authorization-runtime
- Parallel lane: lig-auth-runtime
- Resource class: cpu-proof-solver
- Goal: Compose applicable native-logic evidence into explicit permission, non-conflict, hard-safety, obligation, consistency, translation/reconstruction, and coverage proof jobs; return a context-bound decision/receipt; and permit dispatch only through a short-lived, audience-bound, atomically single-use capability.
- Evidence: LIG-033, LIG-034, LIG-035, LIG-036, LIG-037, LIG-038
- Evidence criteria: decision truth-table and backend-order/disagreement/timeout tests pass; `ALLOW` requires every configured positive gate; compatibility maps deny to reject and review/indeterminate/error to abstain; receipt mutations to actor/audience/tool/arguments/effect/environment/policy/corpus/revocation/nonce/expiry fail; concurrent one-time consumption permits at most one exact dispatch; supervisor/MCP bridges reject every non-allow.
- Evidence source policy: Fresh obligation, portfolio, decision, receipt, service, race/TOCTOU, tenant-cache, supervisor, MCP, and API receipts qualify. SAT alone, no retrieved deny, model confidence, monitor/evidence/policy status, unconsumed bearer data, or a service result without dispatcher revalidation does not.
- Outputs: ipfs_datasets_py/logic/admissibility/compose.py, ipfs_datasets_py/logic/admissibility/portfolio.py, ipfs_datasets_py/logic/admissibility/receipt.py, ipfs_datasets_py/logic/admissibility/service.py, ipfs_datasets_py/logic/admissibility/enforcement.py, ipfs_datasets_py/logic/admissibility/runtime.py, ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py, ipfs_datasets_py/mcp_server/tools/logic_admissibility_tools.py
- Predicted files: ipfs_datasets_py/logic/admissibility/compose.py, ipfs_datasets_py/logic/admissibility/portfolio.py, ipfs_datasets_py/logic/admissibility/receipt.py, ipfs_datasets_py/logic/admissibility/service.py, ipfs_datasets_py/logic/admissibility/enforcement.py, ipfs_datasets_py/logic/admissibility/runtime.py, ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py, ipfs_datasets_py/mcp_server/tools/logic_admissibility_tools.py
- Interfaces: AuthorizationQueryComposer@1, AuthorizationPortfolio@1, DecisionReceipt@1, IntentAuthorizationService@1, PreInvocationEnforcement@1
- Validation: python -m pytest tests/unit/logic/admissibility tests/unit/mcp_server/test_logic_admissibility_tools.py -q
- Acceptance: Native logic families remain typed; deny overrides; positive grant and non-conflict are distinct proof jobs; decisions never adopt proof authority; evaluation has no side effect; decision-cache identity cannot cross a security-relevant context; dispatch revalidates exact current roots/environment and consumes once atomically; bridges import lazily and never execute rejected content.
- Gap task: Close the highest-risk composition, portfolio, receipt, service, cache, dispatch, supervisor, MCP, or API boundary with a semantic or concurrent mutation test.
- Refinement: Keep composer/portfolio, receipt, service, enforcement/runtime, supervisor, and MCP/API leaves separate; preserve allow/reject/abstain compatibility; reserve final exports for the release goal.
- Embedding query: explicit permission non conflict security invariant obligation authorization decision receipt nonce expiry one time dispatch TOCTOU supervisor MCP
- AST query: AuthorizationQueryComposer AuthorizationPortfolio DecisionReceipt IntentAuthorizationService PreInvocationEnforcer

## LIG-G120 Adversarial conformance, governance, rollout, and release

- Status: active
- Parent: LIG-G080, LIG-G110
- Fib priority: 8
- Track: quality
- Priority: P1
- Bundle: lig/authorization-release
- Parallel lane: lig-auth-release
- Resource class: cpu-validation
- Goal: Gate promotion on a reviewable adversarial corpus, privacy-preserving telemetry, deterministic replay, cross-domain conformance, native/ZK differential checks, cache/revocation and tenant isolation, replay/race/TOCTOU and chaos tests, human approvals, and an evidence-preserving rollback drill.
- Evidence: LIG-039, LIG-040, LIG-041
- Evidence criteria: golden, adversarial, metamorphic, differential, deterministic-rebuild, native/ZK, cache/revocation, tenant/privacy, concurrency/TOCTOU, chaos, legacy compatibility, end-to-end, rollout and rollback populations pass on the exact release tree with zero authority-boundary, secret-leakage, and simulated-proof production-authorization violations.
- Evidence source policy: A fresh integrity-bound release receipt enumerating selected tests, optional-capability coverage, code tree, policy/corpus/revocation roots, circuits/VKs, fixture manifests, telemetry/redaction policy, known gaps, human approvals, staged promotion and rollback result qualifies. Documentation, skipped capabilities, one passing fixture, or task-board drainage does not.
- Outputs: ipfs_datasets_py/logic/admissibility/telemetry.py, config/intent_authorization_rollout.json, tests/fixtures/logic/attested_authorization/manifest.json, tests/integration/logic/test_attested_intent_authorization.py, docs/implementation/runbooks/logic_intent_legal_gate_rollout.md, docs/guides/ATTESTED_INTENT_AUTHORIZATION.md
- Predicted files: ipfs_datasets_py/logic/admissibility/telemetry.py, config/intent_authorization_rollout.json, tests/fixtures/logic/attested_authorization, tests/integration/logic/test_attested_intent_authorization.py, docs/implementation/runbooks/logic_intent_legal_gate_rollout.md, docs/guides/ATTESTED_INTENT_AUTHORIZATION.md
- Interfaces: AuthorizationTelemetry@1, AttestedAuthorizationGoldenCorpus@1, AttestedAuthorizationConformance@1, AttestedAuthorizationRollout@1
- Validation: python -m pytest tests/unit/logic/admissibility/test_telemetry.py tests/unit/logic/admissibility/test_attested_golden_contract.py tests/integration/logic/test_attested_intent_authorization.py -q
- Acceptance: Fixtures cover all source kinds and allow/deny/conditional/exception/ambiguous/conflicting/missing/expired/superseded/revoked/poisoned/tampered/simulated/replayed/cross-tenant/exhaustion scenarios; metrics use bounded redacted labels; rollout defaults off/audit then shadow; production allow canary is reversible and allowlisted; circuit/VK/corpus/policy promotion and rollback require explicit approval and exact-root evidence.
- Gap task: Close the highest-risk fixture, privacy/telemetry, conformance, compatibility, governance, promotion, incident, or rollback gap without weakening a failing expectation.
- Refinement: Build telemetry/config and fixture leaves independently; perform shared exports, registry wiring, full integration, runbook/guide update, release evidence, and rollback drill once in the terminal task.
- Embedding query: adversarial authorization conformance privacy telemetry ZKP cache revocation tenant replay race TOCTOU chaos shadow canary rollback release
- AST query: AuthorizationTelemetry AttestedAuthorizationGoldenCorpus AttestedAuthorizationConformance AuthorizationReleaseReceipt
