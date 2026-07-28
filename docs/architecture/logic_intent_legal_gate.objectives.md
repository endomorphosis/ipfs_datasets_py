# Logic Intent · Legal · Security Gate Objective Heap

This objective heap is the durable source of intent for the LIG program:
reuse LegalIR formalization tooling for IntentIR, cache and ZKP-attest
Legal/Security/Intent formal artifacts, query that corpus, and admit or reject
intentions (skills, prompts, MCP tools) under Legal+Security constraints.

Companion files:

- Plan: [`LOGIC_INTENT_LEGAL_GATE_PLAN.md`](./LOGIC_INTENT_LEGAL_GATE_PLAN.md)
- Todo board: [`logic_intent_legal_gate.todo.md`](./logic_intent_legal_gate.todo.md)
  (**sole active** implementation board; IRF board absorbed)
- Predecessor: [`IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`](./IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md)
  / [`ir_family_refactor_intent_ir.todo.md`](./ir_family_refactor_intent_ir.todo.md)
  (IRF **37/37 completed** — do not re-run or co-launch)

## Unified board merge (no duplication / contention / locks)

| Concern | Rule |
|---------|------|
| Duplication | IRF-delivered formalization spine, Intent formalizer, Legal measured path, and Security formalization adapter are **foundation** (LIG-002/004/010 completed; LIG-003 residual CID hygiene only). Net-new work starts at prompt/MCP adapters, proof caches, proof_corpus, admissibility, supervisor/MCP. |
| Contention | Single board namespace `logic-intent-legal-gate-v1`. Do **not** run `ir-family-v1` implementation supervisors while this board is active. |
| Locks / state | Isolated state + worktree roots under `data/agent_supervisor/logic_intent_legal_gate/` (and optional XDG `…/agent-supervisor/logic-intent-legal-gate-v1/`). Never share with IRF/ASREF. |
| Gaps | See todo absorption table + residual LIG-003; missing packages remain LIG-005–020. |

Program invariants:

- Work lands on branch `feature/logic-intent-legal-gate` (datasets) until cutover;
  accelerate-side wiring may use a matching branch only for LIG-G070.
- IntentIR never executes skill/prompt/MCP text; GraphRAG/LLM/advisor never
  become theorem proof authority.
- Proof, monitor, evidence-gate, policy, and ZKP-verify authorities remain
  non-substitutable (`ir_core.protocols.AuthorityKind`).
- Fail closed: missing attestation, integrity failure, unsupported semantics,
  or incomplete constraints → abstain or reject, never silent allow.
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
- Evidence: LIG-G010, LIG-G020, LIG-G030, LIG-G040, LIG-G050, LIG-G060, LIG-G070, LIG-G080
- Evidence criteria: all child goals have fresh current-tree validation; composite gate fixtures cover allow, legal-reject, security-reject, and abstain; ZKP verify fails closed when required; supervisor/MCP entry points load without heavy prover import side effects.
- Evidence source policy: A root receipt must enumerate every child goal terminal receipt, bind repository tree digests and policy/profile versions, and report zero authority-boundary or execution violations. Model narrative and task-board drainage alone do not qualify.
- Outputs: docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md, docs/architecture/logic_intent_legal_gate.objectives.md, docs/architecture/logic_intent_legal_gate.todo.md, tests/integration/logic/test_intent_admissibility_gate.py
- Predicted files: tests/integration/logic/test_intent_admissibility_gate.py, ipfs_datasets_py/logic
- Interfaces: IntentAdmissibilityGate@1, ProofCorpusQuery@1
- Validation: python -m pytest tests/integration/logic/test_intent_admissibility_gate.py -q
- Acceptance: Offline fixtures prove end-to-end lineage from Intent source to gate decision with bound Legal and Security constraint CIDs; optional ZKP verify is profile-gated; no source instructions execute; public Python/MCP APIs document allow/reject/abstain.
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
