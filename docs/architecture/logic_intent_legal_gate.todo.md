# Logic Intent · Legal · Security Gate Task Board (unified / deduplicated)

Executable projection of
[`logic_intent_legal_gate.objectives.md`](./logic_intent_legal_gate.objectives.md).
Human plan:
[`LOGIC_INTENT_LEGAL_GATE_PLAN.md`](./LOGIC_INTENT_LEGAL_GATE_PLAN.md).
Authority/applicability/receipt/enforcement design:
[`INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`](./INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md).

## Merge / deduplication policy (IRF + LIG)

This is the **sole active** implementation board for logic IR family work.

| Predecessor | Status | Policy on this board |
|-------------|--------|----------------------|
| `ir_family_refactor_intent_ir.todo.md` (IRF-*) | **37/37 completed** | Absorbed as foundation. **Do not re-execute IRF tasks.** Do not launch `ir-family-v1` supervisors concurrently with this board. |
| LIG net-new (proof corpus, caches, gate, MCP, supervisor) | pending | Own non-overlapping bundles only (below). |

**No dual boards / no locks contention:**

- Board namespace: `logic-intent-legal-gate-v1` only.
- State roots live under `data/agent_supervisor/logic_intent_legal_gate/` (and optional
  `~/.local/share/ipfs_accelerate_py/agent-supervisor/logic-intent-legal-gate-v1/`).
- Never share state or worktree roots with `ir-family-v1`, ASREF, or other programs.
- Protected operator inputs (read-only for implementation agents):
  - `docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md`
  - `docs/architecture/logic_intent_legal_gate.objectives.md`
  - `docs/architecture/logic_intent_legal_gate.todo.md`
- Shared package `__init__.py` / registry files change only in designated integration tasks.
- Completion requires the task `Validation` command to pass on the current tree.
- Intent never executes skills/prompts/MCP bodies; fail closed on integrity/ZKP gaps.

### Foundation absorption (IRF-delivered; do not reimplement)

Evidence snapshot (2026-07-28, branch `feature/logic-intent-legal-gate`):

| Capability | Evidence on tree | Board treatment |
|------------|------------------|-----------------|
| Shared formalization Protocol | `logic/formalization/compiler.py` (`FormalizationCompiler`); package export | LIG-002 **completed** |
| Formalization contract tests | `tests/unit/logic/formalization/test_contracts.py` (10 passed) | LIG-002 |
| Legal measured compiler path | `legal_ir/canonical_{compiler,decompiler,roundtrip,contracts}.py` | LIG-003 **gap residual** (one frozen CID assert) |
| Intent formalizer implements protocol | `IntentFormalizationCompiler(FormalizationCompiler)` + formalize tests (4 passed) | LIG-004 **completed** |
| Security formalization adapter | `security_ir/formalization_adapter.py` + unit tests (8 passed) | LIG-010 **completed** |
| SkillCenter intent sources | `intent_ir/source_adapters/skillcenter.py` etc. | foundation; prompt/MCP still LIG-005 |

### Parallel waves (net-new only)

```text
Wave 0  (done / residual)  formalization spine + Legal CID hygiene (LIG-003)
Wave 1  parallel lanes:
          lig-intent-sources   LIG-005
          lig-legal-cache      LIG-007 → LIG-008
          lig-security-cache   LIG-009
          lig-gate-profiles    LIG-014
          lig-bootstrap        LIG-021 (ops; non-blocking)
Wave 2  LIG-006 (intent fixtures) after LIG-004+005
Wave 3  LIG-011 → LIG-012 / LIG-013  (proof_corpus)
Wave 4  LIG-015 → LIG-016  (gate)
Wave 5  LIG-017 / LIG-018  (supervisor + MCP)
Wave 6  LIG-019 / LIG-020  (eval + runbook)
Wave 7  LIG-022 / LIG-023  (invocation + constraint contracts)
Wave 8  LIG-024..028       (source adapters + Legal/Security applicability)
Wave 9  LIG-029 → LIG-030 / LIG-031 / LIG-032
Wave 10 LIG-033 → LIG-034 / LIG-039 / LIG-040 → LIG-035
Wave 11 LIG-036 / LIG-037 / LIG-038 → LIG-041
```

## LIG-001 Create branch and freeze LIG architecture docs

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P0
- Track: bootstrap
- Depends on:
- Goal id: LIG-G000
- Outputs: docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md, docs/architecture/logic_intent_legal_gate.objectives.md, docs/architecture/logic_intent_legal_gate.todo.md
- Validation: test -f docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md && test -f docs/architecture/logic_intent_legal_gate.objectives.md && test -f docs/architecture/logic_intent_legal_gate.todo.md
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/root
- Parallel lane: lig-bootstrap
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 4000
- Predicted files: docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md, docs/architecture/logic_intent_legal_gate.objectives.md, docs/architecture/logic_intent_legal_gate.todo.md
- Allow concurrent with:
- Conflict policy: Documentation only; no production logic edits.
- Preconditions: Working tree can create branch from origin/main.
- Effects: Commit plan/objectives/todo; open feature branch.
- Acceptance: Three architecture files exist; DAG and bundles match the plan; branch `feature/logic-intent-legal-gate` exists.
- Evidence: Branch created; unified board documents IRF absorption; ops launch scripts under `scripts/ops/logic_intent_legal_gate/`.

## LIG-002 Extract shared formalization protocols without domain imports

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P0
- Track: formalization
- Depends on: LIG-001
- Goal id: LIG-G010
- Outputs: ipfs_datasets_py/logic/formalization/compiler.py, tests/unit/logic/formalization/test_contracts.py
- Validation: python -m pytest tests/unit/logic/formalization/test_contracts.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/formalization-shared
- Parallel lane: lig-formal-shared
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/logic/formalization, tests/unit/logic/formalization
- Allow concurrent with:
- Conflict policy: Foundation absorbed from IRF; do not re-extract unless import boundary regresses.
- Preconditions: ir_core protocols and formalization modules present.
- Effects: `FormalizationCompiler` Protocol + config live under domain-neutral formalization; no legal_ir import required for protocol use.
- Acceptance: Protocols are backend-neutral; Legal and Intent implement without circular imports.
- Evidence: `FormalizationCompiler` Protocol in `formalization/compiler.py`; `test_contracts.py` green (10). Plan-named `protocols.py` is not required: protocol surface is the compiler module export (package `__init__` re-exports).

## LIG-003 Align Legal measured compiler with shared protocols (residual CID hygiene)

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: formalization
- Depends on: LIG-001
- Goal id: LIG-G010
- Outputs: tests/unit/logic/legal_ir/test_canonical_compiler.py, ipfs_datasets_py/logic/legal_ir/canonical_compiler.py
- Validation: python -m pytest tests/unit/logic/legal_ir/test_canonical_compiler.py tests/unit/logic/legal_ir/test_canonical_decompiler.py tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py tests/unit/logic/legal_ir/test_formalization_adapter.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/formalization-shared
- Parallel lane: lig-formal-legal
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 6000
- Predicted files: ipfs_datasets_py/logic/legal_ir, tests/unit/logic/legal_ir
- Allow concurrent with: LIG-005, LIG-009, LIG-014
- Conflict policy: Legal measured path + frozen fixture CIDs only; no Intent formalize edits; no Security model edits; no proof_cache yet (LIG-007).
- Preconditions: IRF Legal canonical path present (completed foundation).
- Effects: Restore green legal measured suite. Known residual: `test_frozen_cases_reproduce_benchmark_adapter_l1_exactly` CID drift (`bafkrei…` mismatch on adapter path bytes). Fix by regenerating frozen adapter fixture digest or reconciling intentional compiler output change with documented CID update — **do not** weaken integrity checks.
- Acceptance: All four validation modules green; CIDs stable for golden corpus after deliberate update; Legal adapter still implements shared FormalizationCompiler contracts.
- Gap task: Fix only the frozen benchmark adapter L1 CID assertion (or its fixture); do not rewrite Legal autoencoder paths.

## LIG-004 Intent formalizer implements shared compiler protocol

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-002
- Goal id: LIG-G020
- Outputs: ipfs_datasets_py/logic/intent_ir/formalize/compiler.py, ipfs_datasets_py/logic/intent_ir/formalize/obligations.py, tests/unit/logic/intent_ir/formalize/test_compiler.py
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/intent-compile
- Parallel lane: lig-intent-formal
- Resource class: cpu-proof-type-check
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/logic/intent_ir/formalize, tests/unit/logic/intent_ir/formalize
- Allow concurrent with:
- Conflict policy: Foundation absorbed; subsequent intent work is LIG-005/LIG-006 only.
- Preconditions: Shared protocols; Intent schema validates.
- Effects: Deterministic Intent → formal views + obligation digests; GraphRAG premises as assumptions only.
- Acceptance: Protocol conformance tests; semantic mutation changes obligations; no execution of skill text.
- Evidence: `IntentFormalizationCompiler` implements `FormalizationCompiler`; formalize unit tests green (compiler/advisor/round_trip).

## LIG-005 Prompt and MCP tool Intent source adapters

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-001
- Goal id: LIG-G020
- Outputs: ipfs_datasets_py/logic/intent_ir/source_adapters/prompt.py, ipfs_datasets_py/logic/intent_ir/source_adapters/mcp_tool.py, tests/unit/logic/intent_ir/source_adapters/test_prompt_mcp.py, tests/fixtures/intent_ir/prompt_mcp
- Validation: python -m pytest tests/unit/logic/intent_ir/source_adapters/test_prompt_mcp.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/intent-compile
- Parallel lane: lig-intent-sources
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/logic/intent_ir/source_adapters, tests/unit/logic/intent_ir/source_adapters, tests/fixtures/intent_ir/prompt_mcp
- Allow concurrent with: LIG-003, LIG-007, LIG-009, LIG-014
- Conflict policy: New adapters only (`prompt.py`, `mcp_tool.py`, exclusive tests/fixtures); do not change SkillCenter SQLite reader behavior; do not edit formalize/compiler.py.
- Preconditions: Intent schema + SourceRef patterns; skillcenter adapter as pattern reference.
- Effects: Normalize prompts and MCP tool schemas into IntentIR-compatible records with bounds, quarantine, and non-execution policy.
- Acceptance: Adversarial injection fixtures fail closed; identity digests stable; SkillCenter path unchanged.

## LIG-006 Offline Intent formalization fixtures for gate inputs

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-004, LIG-005
- Goal id: LIG-G020
- Outputs: tests/fixtures/intent_ir/admissibility/manifest.json, tests/fixtures/intent_ir/admissibility, tests/unit/logic/intent_ir/formalize/test_admissibility_fixtures.py
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize/test_admissibility_fixtures.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/intent-compile
- Parallel lane: lig-intent-fixtures
- Resource class: io-artifact
- Token class: medium
- Estimated tokens: 8000
- Predicted files: tests/fixtures/intent_ir/admissibility, tests/unit/logic/intent_ir/formalize/test_admissibility_fixtures.py
- Allow concurrent with: LIG-007, LIG-009
- Conflict policy: Fixture tree + one test module only; no production compiler redesign.
- Preconditions: Compiler produces obligations (LIG-004 done); prompt/MCP adapters exist.
- Effects: At least four frozen Intent formal artifacts: benign skill, legally risky effect, security-sensitive resource access, incomplete/unsupported semantics.
- Acceptance: Manifest binds CIDs and expected gate outcomes; rebuild is deterministic.

## LIG-007 Legal proof cache put/get with integrity rehash

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-proof
- Depends on: LIG-003
- Goal id: LIG-G030
- Outputs: ipfs_datasets_py/logic/legal_ir/proof_cache.py, tests/unit/logic/legal_ir/test_proof_cache.py, tests/fixtures/legal_ir/proof_cache
- Validation: python -m pytest tests/unit/logic/legal_ir/test_proof_cache.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/legal-proof-cache
- Parallel lane: lig-legal-cache
- Resource class: io-artifact
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/logic/legal_ir/proof_cache.py, tests/unit/logic/legal_ir/test_proof_cache.py, tests/fixtures/legal_ir/proof_cache
- Allow concurrent with: LIG-005, LIG-009, LIG-014
- Conflict policy: Owns legal `proof_cache.py` module and fixtures only; do not edit Intent formalize; do not edit security_ir.
- Preconditions: Legal formal artifacts can be produced offline; LIG-003 suite green.
- Effects: Content-addressed cache for legal formal artifacts + theorem receipts; fail closed on digest mismatch.
- Acceptance: Hit/miss tests; corruption detection; index by source digest and profile.

## LIG-008 Legal constraint ZKP attestation path

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: legal-proof
- Depends on: LIG-007
- Goal id: LIG-G030
- Outputs: ipfs_datasets_py/logic/zkp/statements/legal_constraint.py, tests/unit/logic/zkp/test_legal_constraint_attestation.py
- Validation: python -m pytest tests/unit/logic/zkp/test_legal_constraint_attestation.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/legal-proof-cache
- Parallel lane: lig-legal-zkp
- Resource class: cpu-proof-translate
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/logic/zkp/statements, tests/unit/logic/zkp
- Allow concurrent with: LIG-010, LIG-011
- Conflict policy: New `zkp/statements/` package + tests; do not change unrelated eth/onchain demos unless required for shared APIs.
- Preconditions: Legal cache stores theorem digests.
- Effects: Prove/verify optional ZKP over pinned statement of legal constraint digest; simulated backend labeled separately from production.
- Acceptance: Verify success on honest proof; verify fail on tampered statement; zkp-required profiles can require this path later.

## LIG-009 Security constraint cache put/get

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: security-proof
- Depends on: LIG-001
- Goal id: LIG-G040
- Outputs: ipfs_datasets_py/logic/security_ir/constraint_cache.py, tests/unit/logic/security_ir/test_constraint_cache.py, tests/fixtures/security_ir/constraint_cache
- Validation: python -m pytest tests/unit/logic/security_ir/test_constraint_cache.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/security-proof-cache
- Parallel lane: lig-security-cache
- Resource class: io-artifact
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/logic/security_ir/constraint_cache.py, tests/unit/logic/security_ir/test_constraint_cache.py, tests/fixtures/security_ir/constraint_cache
- Allow concurrent with: LIG-003, LIG-005, LIG-007, LIG-014
- Conflict policy: New `constraint_cache.py` + exclusive tests/fixtures only; preserve IRF Security freeze contracts; do not rewrite `formalization_adapter.py` (LIG-010 done).
- Preconditions: SecurityIR model/adapters available (IRF foundation).
- Effects: Cache formalized security constraints and policy decisions with integrity.
- Acceptance: Exchange + Xaman sample constraints cache/reload; unknown extensions fail closed.

## LIG-010 Security formalization adapter protocol alignment

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P1
- Track: security-proof
- Depends on: LIG-002
- Goal id: LIG-G040
- Outputs: ipfs_datasets_py/logic/security_ir/formalization_adapter.py, tests/unit/logic/security_ir/test_formalization_adapter.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_formalization_adapter.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/security-proof-cache
- Parallel lane: lig-security-formal
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/logic/security_ir/formalization_adapter.py, tests/unit/logic/security_ir/test_formalization_adapter.py
- Allow concurrent with:
- Conflict policy: Foundation absorbed; cache work is LIG-009 only.
- Preconditions: Shared protocols.
- Effects: Security declarations lower to formal constraints via shared FormalizationCompiler contracts.
- Acceptance: Protocol conformance; authority kinds preserved for policy vs theorem.
- Evidence: Adapter present; unit tests green (8).

## LIG-011 Proof corpus store package and schemas

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-006, LIG-007, LIG-009
- Goal id: LIG-G050
- Outputs: ipfs_datasets_py/logic/proof_corpus/__init__.py, ipfs_datasets_py/logic/proof_corpus/schemas.py, ipfs_datasets_py/logic/proof_corpus/store.py, tests/unit/logic/proof_corpus/test_store.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_store.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-store
- Parallel lane: lig-store
- Resource class: io-artifact
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/logic/proof_corpus, tests/unit/logic/proof_corpus
- Allow concurrent with:
- Conflict policy: New `proof_corpus` package only; family caches remain sources of fixtures.
- Preconditions: Offline fixtures for Intent/Legal/Security formal artifacts exist.
- Effects: Put/get envelopes by CID; rehash integrity; multi-family support.
- Acceptance: Store accepts three family fixtures; corruption fails closed.

## LIG-012 Proof corpus query API

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-011
- Goal id: LIG-G050
- Outputs: ipfs_datasets_py/logic/proof_corpus/query.py, ipfs_datasets_py/logic/proof_corpus/index.py, tests/unit/logic/proof_corpus/test_query.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_query.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-store
- Parallel lane: lig-store-query
- Resource class: io-artifact
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/logic/proof_corpus/query.py, ipfs_datasets_py/logic/proof_corpus/index.py, tests/unit/logic/proof_corpus/test_query.py
- Allow concurrent with: LIG-013
- Conflict policy: Query/index modules only under proof_corpus.
- Preconditions: Store populated in tests via fixtures.
- Effects: Queries by source, family, obligation digest, profile; rebuildable indexes.
- Acceptance: Deterministic query results; index rebuild matches.

## LIG-013 Attestation verify helper in proof corpus

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: proof-store
- Depends on: LIG-011, LIG-008
- Goal id: LIG-G050
- Outputs: ipfs_datasets_py/logic/proof_corpus/attest.py, tests/unit/logic/proof_corpus/test_attest.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_attest.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-store
- Parallel lane: lig-store-attest
- Resource class: cpu-proof-translate
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/logic/proof_corpus/attest.py, tests/unit/logic/proof_corpus/test_attest.py
- Allow concurrent with: LIG-012
- Conflict policy: attest module + test only.
- Preconditions: ZKP verify APIs available.
- Effects: verify_attestation(cid, profile) returns typed pass/fail/absent.
- Acceptance: Honest legal fixture verifies when present; missing ZKP is absent not pass.

## LIG-014 Admissibility profiles and reason codes

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-001
- Goal id: LIG-G060
- Outputs: ipfs_datasets_py/logic/admissibility/profiles.py, ipfs_datasets_py/logic/admissibility/reasons.py, tests/unit/logic/admissibility/test_profiles.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_profiles.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/admissibility-gate
- Parallel lane: lig-gate-profiles
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 6000
- Predicted files: ipfs_datasets_py/logic/admissibility, tests/unit/logic/admissibility
- Allow concurrent with: LIG-003, LIG-005, LIG-007, LIG-009, LIG-011, LIG-012
- Conflict policy: `profiles.py`/`reasons.py` + exclusive test only; no gate join logic yet (LIG-015).
- Preconditions: Plan defines profile names.
- Effects: Profiles dev-offline, security-lite, legal-strict, zkp-required; closed reason vocabulary.
- Acceptance: Invalid profile fails closed; reason codes are enum-stable.

## LIG-015 Composite admissibility gate core

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-012, LIG-013, LIG-014, LIG-006
- Goal id: LIG-G060
- Outputs: ipfs_datasets_py/logic/admissibility/gate.py, ipfs_datasets_py/logic/admissibility/__init__.py, tests/unit/logic/admissibility/test_gate.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_gate.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/admissibility-gate
- Parallel lane: lig-gate-core
- Resource class: cpu-validation
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/logic/admissibility, tests/unit/logic/admissibility
- Allow concurrent with:
- Conflict policy: Gate package join logic; consumes proof_corpus query only via public API.
- Preconditions: Proof corpus query + fixtures + profiles.
- Effects: evaluate(intent_formal_cid | IntentIR, profile) → allow/reject/abstain with bound CIDs.
- Acceptance: Unit tests for four outcome classes; deterministic for fixed store snapshot.

## LIG-016 Integration test for end-to-end admissibility

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-015
- Goal id: LIG-G060
- Outputs: tests/integration/logic/test_intent_admissibility_gate.py, tests/fixtures/logic/admissibility
- Validation: python -m pytest tests/integration/logic/test_intent_admissibility_gate.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/admissibility-gate
- Parallel lane: lig-gate-e2e
- Resource class: cpu-validation
- Token class: large
- Estimated tokens: 12000
- Predicted files: tests/integration/logic/test_intent_admissibility_gate.py, tests/fixtures/logic/admissibility
- Allow concurrent with: LIG-017
- Conflict policy: Integration tests/fixtures only.
- Preconditions: Gate core complete.
- Effects: Offline multi-family corpus → gate decisions for allow/legal-reject/security-reject/abstain.
- Acceptance: Full lineage CIDs asserted; no network required.

## LIG-017 Supervisor admissibility bridge

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: integration
- Depends on: LIG-015
- Goal id: LIG-G070
- Outputs: ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py, test/api/test_agent_supervisor_intent_admissibility.py
- Validation: python -m pytest test/api/test_agent_supervisor_intent_admissibility.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/supervisor-integration
- Parallel lane: lig-supervisor
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py, ipfs_accelerate_py/agent_supervisor/ir_registry.py, test/api/test_agent_supervisor_intent_admissibility.py
- Allow concurrent with: LIG-018
- Conflict policy: Accelerate bridge + focused test; minimize ir_registry surface changes; no datasets formalize rewrites. Prefer branch `feature/logic-intent-legal-gate` on accelerate only if needed.
- Preconditions: Datasets gate importable as optional dependency.
- Effects: Bridge loads pinned artifacts and returns decision objects to supervisor; lazy imports.
- Acceptance: Import agent_supervisor without provers; bridge unit test with mocked corpus or offline fixtures.

## LIG-018 MCP tools for normalize formalize query check

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: integration
- Depends on: LIG-015
- Goal id: LIG-G070
- Outputs: ipfs_datasets_py/mcp_server/tools/logic_admissibility_tools.py, tests/unit/mcp_server/test_logic_admissibility_tools.py
- Validation: python -m pytest tests/unit/mcp_server/test_logic_admissibility_tools.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/supervisor-integration
- Parallel lane: lig-mcp
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/mcp_server, tests/unit/mcp_server
- Allow concurrent with: LIG-017
- Conflict policy: New MCP tool module + test; do not rewrite unrelated MCP servers.
- Preconditions: Gate public API stable.
- Effects: Tools: normalize_intent, formalize_intent, query_proof_corpus, check_intent_admissibility; schemas documented.
- Acceptance: Tool handlers fail closed; never execute skill/prompt bodies.

## LIG-019 Admissibility benchmark and leakage guards

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: quality
- Depends on: LIG-016
- Goal id: LIG-G080
- Outputs: tests/benchmarks/logic/test_intent_admissibility_benchmark.py, tests/fixtures/logic/admissibility/benchmark
- Validation: python -m pytest tests/benchmarks/logic/test_intent_admissibility_benchmark.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/eval-rollout
- Parallel lane: lig-eval
- Resource class: cpu-validation
- Token class: medium
- Estimated tokens: 8000
- Predicted files: tests/benchmarks/logic, tests/fixtures/logic/admissibility/benchmark
- Allow concurrent with: LIG-020
- Conflict policy: Benchmark fixtures/tests only.
- Preconditions: Integration fixtures exist.
- Effects: Held-out sources; metrics for allow/reject/abstain; no train/test leakage.
- Acceptance: Benchmark is offline and deterministic.

## LIG-020 Rollout runbook shadow and canary

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: quality
- Depends on: LIG-016, LIG-017
- Goal id: LIG-G080
- Outputs: docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
- Validation: test -f docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/eval-rollout
- Parallel lane: lig-docs
- Resource class: cpu-small
- Token class: small
- Estimated tokens: 4000
- Predicted files: docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
- Allow concurrent with: LIG-019
- Conflict policy: New runbook only; do not edit protected plan/objectives/todo unless operator-approved.
- Preconditions: Gate + bridge exist.
- Effects: Shadow default; canary criteria; rollback; operator launch commands for agent supervisor board.
- Acceptance: Runbook lists profiles, protected paths, and validation commands.

## LIG-021 Multi-lane supervisor launch recipe for LIG board

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P1
- Track: bootstrap
- Depends on: LIG-001
- Goal id: LIG-G000
- Outputs: scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh, scripts/ops/logic_intent_legal_gate/README.md, docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md
- Validation: test -f scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh && test -x scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/root
- Parallel lane: lig-bootstrap
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 5000
- Predicted files: scripts/ops/logic_intent_legal_gate, docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md
- Allow concurrent with:
- Conflict policy: Ops docs/scripts only.
- Preconditions: Board committed.
- Effects: Document objective-daemon (optional) and multi-lane implementation-supervisor commands with protected-path flags; isolate state from ir-family-v1.
- Acceptance: Operator can launch parallel lanes without reading other programs; dry-run `--once --no-implement` succeeds.
- Evidence: Launch scripts + plan § Supervisor operation updated for unified board.

## LIG-022 Define the canonical invocation intent envelope

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: authorization-contract
- Depends on: LIG-004, LIG-005
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/intent_ir/invocation/__init__.py, ipfs_datasets_py/logic/intent_ir/invocation/model.py, tests/unit/logic/intent_ir/invocation/test_model.py
- Validation: python -m pytest tests/unit/logic/intent_ir/invocation/test_model.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-contracts
- Parallel lane: lig-invocation-envelope
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/logic/intent_ir/invocation/__init__.py, ipfs_datasets_py/logic/intent_ir/invocation/model.py, tests/unit/logic/intent_ir/invocation/test_model.py
- Interfaces: InvocationIntentEnvelope@1
- Allow concurrent with: LIG-023
- Conflict policy: Own only the new invocation package model/leaf initializer and test; do not edit completed source adapters, Intent schema/formalizer, domain packages, shared exports, or registry.
- Preconditions: Intent formalization and prompt/MCP source-adapter contracts pass.
- Effects: All skill, prompt, and MCP proposals can bind one immutable, canonical, redaction-aware execution-context contract before evaluation.
- Evidence subset: invocation canonical-byte, mutation, schema, and secret-redaction receipt
- Acceptance: Type and canonically bind source kind/ref, tenant, actor/delegation, audience, tool/server/schema/version, redacted argument commitment, actions/effects/capabilities/assets/resources/data/network/filesystem/subprocess scope, purpose/jurisdiction/time, environment/rollback/verification, policy/corpus requirements, nonce/deadline, source maps, assumptions, diagnostics, and unsupported fields; reject raw secrets, mutation, unknown versions, NaN/unbounded structures, and identity drift.

## LIG-023 Define shared constraint and applicability contracts

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: authorization-contract
- Depends on: LIG-002, LIG-003, LIG-004, LIG-010
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/formalization/constraint_contracts.py, tests/unit/logic/formalization/test_constraint_contracts.py
- Validation: python -m pytest tests/unit/logic/formalization/test_constraint_contracts.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-contracts
- Parallel lane: lig-constraint-contracts
- Resource class: cpu-proof-type-check
- Token class: large
- Estimated tokens: 9500
- Predicted files: ipfs_datasets_py/logic/formalization/constraint_contracts.py, tests/unit/logic/formalization/test_constraint_contracts.py
- Interfaces: ConstraintArtifact@1, ApplicabilityEvidence@1, SelectedPremiseSet@1
- Allow concurrent with: LIG-022
- Conflict policy: Own one domain-neutral leaf and fake-domain tests; import no Legal/Security corpus rules, solver, retriever, model, storage runtime, package exports, or registry.
- Preconditions: Shared formalization and all three domain adapter contracts pass.
- Effects: Legal, Security, and Intent views can expose typed grants, prohibitions, obligations, exceptions, invariants, assumptions, applicability, coverage, and selected-premise receipts without flattening logics.
- Evidence subset: constraint immutability, source-grounding, result-authority, and cross-logic boundary receipt
- Acceptance: Bind domain/logic/source/corpus/config identities, typed native views, vocabulary, applicability selectors/evidence, open/closed-world policy, premise selection, translations/reconstruction, coverage/gaps, diagnostics and stable obligations; reject ungrounded premises, result-authority substitution, unknown logic/schema, mutable collections, and silent modal/Datalog/temporal/Hoare/SMT concatenation.

## LIG-024 Adapt SkillCenter intent into invocation envelopes

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-004, LIG-022
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/intent_ir/invocation/skillcenter.py, tests/unit/logic/intent_ir/invocation/test_skillcenter.py
- Validation: python -m pytest tests/unit/logic/intent_ir/invocation/test_skillcenter.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/invocation-adapters
- Parallel lane: lig-invocation-skillcenter
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 7500
- Predicted files: ipfs_datasets_py/logic/intent_ir/invocation/skillcenter.py, tests/unit/logic/intent_ir/invocation/test_skillcenter.py
- Interfaces: SkillCenterInvocationAdapter@1
- Allow concurrent with: LIG-025, LIG-026, LIG-027, LIG-028
- Conflict policy: Own only the invocation adapter/test; consume the existing pinned SkillCenter source adapter, Intent artifact, and envelope without fetching mutable revisions, editing them, executing commands, or touching exports/registry.
- Preconditions: Invocation envelope and existing SkillCenter-to-Intent/formalization paths pass.
- Effects: A validated pinned skill plus caller/runtime context becomes a bounded proposed invocation with complete source-to-action lineage.
- Evidence subset: pinned skill invocation grounding, context mutation, quarantine, and non-execution receipt
- Acceptance: Require exact snapshot/record/content/Intent/formalization identities and approved source policy; map concrete actor/audience/arguments/actions/effects/capabilities/resources/failures/rollback/verification with source spans; keep unsupported/ambiguous terms; reject quarantined/mutable/mismatched content, prompt injection, secret leakage, missing runtime context, and all source command execution.

## LIG-025 Adapt prompt intent into invocation envelopes

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-005, LIG-022
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/intent_ir/invocation/prompt.py, tests/unit/logic/intent_ir/invocation/test_prompt.py
- Validation: python -m pytest tests/unit/logic/intent_ir/invocation/test_prompt.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/invocation-adapters
- Parallel lane: lig-invocation-prompt
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 7500
- Predicted files: ipfs_datasets_py/logic/intent_ir/invocation/prompt.py, tests/unit/logic/intent_ir/invocation/test_prompt.py
- Interfaces: PromptInvocationAdapter@1
- Allow concurrent with: LIG-024, LIG-026, LIG-027, LIG-028
- Conflict policy: Own only the invocation adapter and hostile fixtures; wrap the completed prompt source adapter without editing it, calling a live model, following content, executing commands, or touching exports/registry.
- Preconditions: Prompt source adapter, formalization, and invocation envelope pass.
- Effects: The user's requested outcome is bound to caller-supplied execution context while quoted, retrieved, and tool-produced content remains non-authoritative data.
- Evidence subset: prompt boundary, context, ambiguity, injection, redaction, and semantic-mutation receipt
- Acceptance: Bind prompt/content digests and exact source segments; distinguish user instruction, quoted data, retrieved evidence and tool output; require explicit actor/audience/tool/arguments/effects/environment; preserve ambiguity/unsupported semantics; bound size/depth; redact sensitive spans; relevant mutations change identity/obligations; no candidate inference invents permission or capability.

## LIG-026 Adapt MCP intent into invocation envelopes

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: intent
- Depends on: LIG-005, LIG-022
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/intent_ir/invocation/mcp.py, tests/unit/logic/intent_ir/invocation/test_mcp.py
- Validation: python -m pytest tests/unit/logic/intent_ir/invocation/test_mcp.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/invocation-adapters
- Parallel lane: lig-invocation-mcp
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 8000
- Predicted files: ipfs_datasets_py/logic/intent_ir/invocation/mcp.py, tests/unit/logic/intent_ir/invocation/test_mcp.py
- Interfaces: MCPInvocationAdapter@1
- Allow concurrent with: LIG-024, LIG-025, LIG-027, LIG-028
- Conflict policy: Own only the invocation adapter/fake-server tests; wrap the completed MCP source adapter without editing it, connecting to a server, invoking a tool, trusting annotations as facts, or touching exports/registry.
- Preconditions: MCP source adapter, formalization, and invocation envelope pass.
- Effects: A concrete MCP call binds server/tool/schema/arguments, caller/delegation, dispatcher audience, and independently resolved host effects before any transport call.
- Evidence subset: MCP identity, argument, capability, confused-deputy, and no-invocation receipt
- Acceptance: Canonically bind server/transport peer/tool/version/input-schema, redacted argument commitment and requested output; record annotations as untrusted claims; bind actual resolved capabilities/effects/audience/environment; reject schema/identity mismatch, oversized/nested/dynamic inputs, secret serialization, caller-controlled dispatcher, unknown capability, and every network/tool call during adaptation.

## LIG-027 Select applicable Legal constraints

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-proof
- Depends on: LIG-003, LIG-007, LIG-023
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/legal_ir/constraint_query.py, tests/unit/logic/legal_ir/test_constraint_query.py
- Validation: python -m pytest tests/unit/logic/legal_ir/test_constraint_query.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/applicability
- Parallel lane: lig-legal-applicability
- Resource class: cpu-proof-select
- Token class: large
- Estimated tokens: 11000
- Predicted files: ipfs_datasets_py/logic/legal_ir/constraint_query.py, tests/unit/logic/legal_ir/test_constraint_query.py
- Interfaces: LegalConstraintQuery@1, LegalApplicabilityEvidence@1
- Allow concurrent with: LIG-024, LIG-025, LIG-026, LIG-028
- Conflict policy: Own one Legal query/applicability leaf and fixtures; call existing canonical compiler, cache, premise/security/temporal APIs without editing them, the proof corpus, Security query, exports, or registry.
- Preconditions: Legal measured path/cache and shared constraint contracts pass.
- Effects: Legal constraints are hard scoped and selected with explicit jurisdiction, authority, time, exception, subject/resource, conflict, source-security, and corpus-coverage evidence.
- Evidence subset: Legal applicability, temporal authority, contradiction, and selected-premise receipt
- Acceptance: Bind jurisdiction/territory/subject matter, authority hierarchy/precedence, enactment/effective/repeal, amendment/supersession, definitions/cross-references/exceptions, actor/subject/resource/purpose/threshold, premise taint/provenance, competing authorities and bounded selection; preserve contradictions; unresolved conflict/applicability/coverage yields review/abstain; retrieval rank alone never selects authority.

## LIG-028 Select applicable Security constraints and evidence

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: security-proof
- Depends on: LIG-009, LIG-010, LIG-023
- Goal id: LIG-G090
- Outputs: ipfs_datasets_py/logic/security_ir/constraint_query.py, tests/unit/logic/security_ir/test_constraint_query.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_constraint_query.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/applicability
- Parallel lane: lig-security-applicability
- Resource class: cpu-proof-select
- Token class: large
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/logic/security_ir/constraint_query.py, tests/unit/logic/security_ir/test_constraint_query.py
- Interfaces: SecurityConstraintQuery@1, SecurityApplicabilityEvidence@1
- Allow concurrent with: LIG-024, LIG-025, LIG-026, LIG-027
- Conflict policy: Own one Security query/applicability leaf and fixtures; consume declarations/formalization/cache/typed results without editing them, the proof corpus, Legal query, exports, or registry.
- Preconditions: Security constraint cache/formalization and shared constraint contracts pass.
- Effects: Security constraints are selected by actual principal, delegation, capability, trust zone, asset, effect, data, environment, threat model, policy, freshness, and result authority.
- Evidence subset: Security applicability, environment-model boundary, and result-authority selection receipt
- Acceptance: Bind principal/delegation/capability, trust zone, asset/data class/channel/network/filesystem, action/state/effect/failure/rollback, sandbox/environment evidence, threat/policy version and freshness; keep theorem, monitor, evidence-gate and policy artifacts distinct; reject stale/mismatched evidence, abstract-model/live-environment substitution, gaps, contradictions, unknown extensions and unbounded selection.

## LIG-029 Define authority-grade proof envelopes and trust policy

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-008, LIG-011, LIG-013, LIG-014
- Goal id: LIG-G100
- Outputs: ipfs_datasets_py/logic/proof_corpus/model.py, ipfs_datasets_py/logic/proof_corpus/policy.py, tests/unit/logic/proof_corpus/test_authority_model_policy.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_authority_model_policy.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-authority
- Parallel lane: lig-proof-authority-contract
- Resource class: cpu-proof-type-check
- Token class: large
- Estimated tokens: 11000
- Predicted files: ipfs_datasets_py/logic/proof_corpus/model.py, ipfs_datasets_py/logic/proof_corpus/policy.py, tests/unit/logic/proof_corpus/test_authority_model_policy.py
- Interfaces: AttestedProofEnvelope@1, ProofTrustPolicy@1, CorpusCoveragePolicy@1
- Allow concurrent with:
- Conflict policy: Add authority model/policy leaves after the base store/query/attestation package; do not rewrite its schemas/store/attest, family caches, ZKP backends, profiles/reasons, exports, or registry.
- Preconditions: Base multi-family proof corpus, Legal constraint attestation, attestation helper, and profile vocabulary pass.
- Effects: Proof cache entries acquire complete immutable authority, scope, freshness, revocation, circuit/VK/public-input, and coverage semantics without silently upgrading legacy records.
- Evidence subset: proof-envelope canonical identity, trust-policy mutation, authority separation, and simulation-rejection receipt
- Acceptance: Bind statement/assumption/obligation, domain/logic/result authority, source/corpus/policy/ontology/adapter/compiler/translation/solver/reconstruction, proof/build/source-map CIDs, attestation kind, circuit/VK/backend/public inputs/security profile, effective/expiry, jurisdiction/tenant/subject/resource scope, coverage, parents, supersession/revocation and diagnostics; policy declares exact roots/allowlists/minimums/budgets/open-closed-world/conflict rules; direct verification, verifier execution, membership, signature and simulation remain non-substitutable.

## LIG-030 Add immutable proof-corpus manifests and revocation snapshots

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-011, LIG-029
- Goal id: LIG-G100
- Outputs: ipfs_datasets_py/logic/proof_corpus/manifest.py, ipfs_datasets_py/logic/proof_corpus/revocation.py, tests/unit/logic/proof_corpus/test_manifest_revocation.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_manifest_revocation.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-authority
- Parallel lane: lig-proof-manifest
- Resource class: io-artifact
- Token class: large
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/logic/proof_corpus/manifest.py, ipfs_datasets_py/logic/proof_corpus/revocation.py, tests/unit/logic/proof_corpus/test_manifest_revocation.py
- Interfaces: ProofCorpusManifest@1, ProofRevocationSnapshot@1
- Allow concurrent with: LIG-031, LIG-032
- Conflict policy: Own manifest/revocation leaves and deterministic local-store tests; consume the base store/authority model without editing schemas/store/query/index/attest, domain caches, exports, or registry.
- Preconditions: Base proof store and authority envelope/policy pass.
- Effects: Corpus bodies, index manifests, registries, parent lineage, coverage and revocation are exact-root, append-only content-addressed snapshots.
- Evidence subset: deterministic corpus rebuild, append-only lineage, tamper, supersession, and revocation receipt
- Acceptance: Bind corpus domain/namespace/schema/root/parent, ordered entries, source set, compiler/solver/circuit/VK registries, index manifests, revocation root, coverage/licensing/privacy/tenant policy, producer and promotion receipt; separate bodies from indices; reject mutable latest, duplicate/missing/unbound bodies, path traversal, oversize content, hash/CID mismatch, parent/revocation cycles, rollback/downgrade and unapproved registry roots.

## LIG-031 Enforce hard-filtered proof query and redacted audit traces

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-012, LIG-029
- Goal id: LIG-G100
- Outputs: ipfs_datasets_py/logic/proof_corpus/applicability.py, ipfs_datasets_py/logic/proof_corpus/audit.py, tests/unit/logic/proof_corpus/test_applicability_audit.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_applicability_audit.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-authority
- Parallel lane: lig-proof-query-authority
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 10500
- Predicted files: ipfs_datasets_py/logic/proof_corpus/applicability.py, ipfs_datasets_py/logic/proof_corpus/audit.py, tests/unit/logic/proof_corpus/test_applicability_audit.py
- Interfaces: ProofApplicabilityFilter@1, ProofQueryAuditReceipt@1
- Allow concurrent with: LIG-030, LIG-032
- Conflict policy: Own hard-filter/audit wrappers and synthetic tests; consume base query/index and authority policy without editing them, implementing body proof verification/domain selection, emitting private content, exports, or registry.
- Preconditions: Base deterministic query and authority model/policy pass.
- Effects: Tenant, root, scope, time, revocation, authority, algorithm and capability filters run before any lexical/graph/dense ranking and every omission is traceable.
- Evidence subset: hard-filter-before-rank, tenant/partition isolation, poisoned-neighbor, bounded query, and redacted replay receipt
- Acceptance: Filter tenant/visibility, exact root lineage, jurisdiction/authority/subject/resource/action/capability/data, effective/expiry, supersession/revocation, policy/schema/logic/backend/circuit/VK and proof authority before bounded rank; trace considered/filtered/ranked/selected/rejected counts/reasons, budgets and gaps; exclude raw prompts/arguments/secrets/witnesses/private formulas and unbounded labels; ranking never establishes applicability or proof.

## LIG-032 Independently verify proof evidence and quarantine legacy caches

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: proof-store
- Depends on: LIG-008, LIG-013, LIG-029
- Goal id: LIG-G100
- Outputs: ipfs_datasets_py/logic/proof_corpus/verifier.py, ipfs_datasets_py/logic/proof_corpus/migration.py, tests/fixtures/proof_corpus/legacy_authority_manifest.json, tests/unit/logic/proof_corpus/test_verifier_migration.py
- Validation: python -m pytest tests/unit/logic/proof_corpus/test_verifier_migration.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/proof-authority
- Parallel lane: lig-proof-verifier
- Resource class: cpu-proof-verify
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/logic/proof_corpus/verifier.py, ipfs_datasets_py/logic/proof_corpus/migration.py, tests/fixtures/proof_corpus/legacy_authority_manifest.json, tests/unit/logic/proof_corpus/test_verifier_migration.py
- Interfaces: AttestedProofVerifier@1, SelectedEvidencePack@1, LegacyProofCorpusReader@1
- Allow concurrent with: LIG-030, LIG-031
- Conflict policy: Own consumer verifier/migration leaves and adversarial fixtures; consume base store/query/attestation and existing caches read-only; do not mutate/delete legacy data, change ZKP backends, edit other proof leaves, exports, or registry.
- Preconditions: Legal ZKP statement, base attestation helper, and authority envelope/policy pass.
- Effects: Every selected body/native proof/ZKP/parent/source/policy/scope/time/revocation binding is checked by the consumer; incomplete legacy cache records remain audit-only until rebuilt.
- Evidence subset: native/ZK proof integrity, circuit/VK/public-input, freshness/revocation, legacy loss, and selected-evidence receipt
- Acceptance: Verify exact roots and all statement/assumption/obligation/source/build/compiler/solver/translation/reconstruction/proof bindings plus approved native or ZK proof, circuit spec/VK/public inputs, tenant/scope/time/expiry/supersession/revocation/coverage/parents; reject producer claims, cache hits, unknown/downgraded algorithms, malformed/underconstrained/forged proofs, real-to-simulation fallback, membership-as-theorem, partial fetch and cross-tenant substitution; legacy reader reports every absent binding and never grants authority.

## LIG-033 Compose authorization obligations and portfolio decisions

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-015, LIG-022, LIG-023, LIG-027, LIG-028, LIG-030, LIG-031, LIG-032
- Goal id: LIG-G110
- Outputs: ipfs_datasets_py/logic/admissibility/compose.py, ipfs_datasets_py/logic/admissibility/portfolio.py, tests/unit/logic/admissibility/test_compose_portfolio.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_compose_portfolio.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-runtime
- Parallel lane: lig-auth-compose
- Resource class: cpu-proof-solver
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/logic/admissibility/compose.py, ipfs_datasets_py/logic/admissibility/portfolio.py, tests/unit/logic/admissibility/test_compose_portfolio.py
- Interfaces: AuthorizationQueryComposer@1, AuthorizationPortfolio@1, AuthorizationDecisionPolicy@1
- Allow concurrent with:
- Conflict policy: Own composition/portfolio leaves and fake backends; consume the base gate, selected domain/corpus evidence and backend protocols without editing them, profiles/reasons, receipts/service/runtime, exports, or registry.
- Preconditions: Base gate, invocation/constraint contracts, both applicability selectors, immutable corpus/query and independently verified evidence packs pass.
- Effects: Each action/effect receives explicit applicability, positive permission, prohibition/non-conflict, hard Security, pre/during/post obligation, consistency, translation/reconstruction, coverage, and context-binding proof jobs with deterministic result selection.
- Evidence subset: semantic obligation mutation, positive-permission/non-conflict, backend order/disagreement/timeout, and authority-selection receipt
- Acceptance: Preserve native logic and typed cross-view links; a closed profile requires an applicable positive grant and proved non-conflict rather than no retrieved deny; include Security invariants, obligations and coverage; probe backends without installation; record capabilities/assumptions/translations/reconstruction/attempts/timeouts; deterministic deny-overrides selection is order independent; unsupported/unknown/contradictory/unavailable/SAT-only/model/monitor/evidence/policy/simulation paths cannot allow; map internal deny to reject and review/indeterminate/error to abstain.

## LIG-034 Implement exact-context decision receipts and capability contracts

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-022, LIG-029, LIG-033
- Goal id: LIG-G110
- Outputs: ipfs_datasets_py/logic/admissibility/receipt.py, tests/unit/logic/admissibility/test_receipt.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_receipt.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-runtime
- Parallel lane: lig-auth-receipt
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 9500
- Predicted files: ipfs_datasets_py/logic/admissibility/receipt.py, tests/unit/logic/admissibility/test_receipt.py
- Interfaces: DecisionReceipt@1, AuthorizationCapability@1
- Allow concurrent with: LIG-039, LIG-040
- Conflict policy: Own immutable receipt/capability codecs and tests; do not implement service/persistence/dispatch/consumption/signing infrastructure, edit composer/portfolio/telemetry/fixtures, exports, or registry.
- Preconditions: Invocation, authority model, and composed decision contracts pass.
- Effects: Decisions become independently checkable and an allow can be attenuated to an exact, short-lived, audience-bound, one-time dispatch capability.
- Evidence subset: receipt identity, outcome mapping, context mutation, attenuation, audience, expiry, and replay receipt
- Acceptance: Bind request/arguments/actor/delegation/audience/tool/effects/environment, selected evidence, obligations/attempts/results, policy/corpus/revocation/circuit/VK roots, outcome/reasons/residual duties, nonce/issued/deadline/expiry and producer; derive capability only from allow, require strict subset attenuation and one-time marker; reject mutation/widening/wrong audience/stale roots/expiry/unknown schema-algorithm and all non-allow derivation.

## LIG-035 Integrate the side-effect-free intent authorization service

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: gate
- Depends on: LIG-016, LIG-030, LIG-031, LIG-032, LIG-033, LIG-034, LIG-040
- Goal id: LIG-G110
- Outputs: ipfs_datasets_py/logic/admissibility/service.py, tests/unit/logic/admissibility/test_authorization_service.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_authorization_service.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-runtime
- Parallel lane: lig-auth-service
- Resource class: cpu-proof-solver
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/logic/admissibility/service.py, tests/unit/logic/admissibility/test_authorization_service.py
- Interfaces: IntentAuthorizationService@1
- Allow concurrent with:
- Conflict policy: Sole owner of exact-context service integration and fake-dependency tests; compose the base gate and new leaves through public APIs without editing them, performing dispatch, adding exports/registry entries, or requiring network/models/optional solvers.
- Preconditions: Base integration, immutable manifest/query/verifier, composer/portfolio, receipt and adversarial contract fixtures pass.
- Effects: One deterministic API evaluates a canonical invocation against exact Legal/Security/Intent corpus and revocation roots and returns compatibility status plus a richer typed decision/receipt.
- Evidence subset: offline source-to-decision service, deterministic replay, cancellation, exception, and no-side-effect receipt
- Acceptance: Validate all inputs/roots/budgets; normalize or accept a canonical envelope; lower Intent; hard-filter/select/verify evidence; compose/run native proof jobs; select/map decision; build receipt; preserve trace/diagnostics; support injected offline dependencies, cancellation and replay; never execute content/tools, install backends, mutate corpus, authorize simulated evidence in production, derive capability for non-allow, or convert exceptions into allow.

## LIG-036 Add tenant-safe decision caching and pre-dispatch enforcement

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: authorization-runtime
- Depends on: LIG-034, LIG-035
- Goal id: LIG-G110
- Outputs: ipfs_datasets_py/logic/admissibility/enforcement.py, ipfs_datasets_py/logic/admissibility/runtime.py, tests/unit/logic/admissibility/test_enforcement_runtime.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_enforcement_runtime.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-runtime
- Parallel lane: lig-auth-enforcement
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/logic/admissibility/enforcement.py, ipfs_datasets_py/logic/admissibility/runtime.py, tests/unit/logic/admissibility/test_enforcement_runtime.py
- Interfaces: PreInvocationEnforcement@1, DecisionCacheKey@1, CapabilityConsumptionStore@1
- Allow concurrent with: LIG-037, LIG-038
- Conflict policy: Own generic pre-dispatch/runtime leaves, in-memory reference stores, fake dispatchers and race tests; do not connect to real tools, edit service/receipt/supervisor/MCP/telemetry, mutate legacy caches, add exports, or touch registry.
- Preconditions: Authorization service and receipt/capability contracts pass.
- Effects: Only an exact current allow receipt can reach a dispatcher, decision reuse cannot cross a security-relevant context, and one-time consumption is atomic under races.
- Evidence subset: non-allow rejection, complete cache-key mutation, tenant isolation, TTL, revocation/environment TOCTOU, and concurrent consumption receipt
- Acceptance: Reject every non-allow; immediately verify actor/delegation/audience/request/arguments/tool/version/effects, nonce/expiry, policy/corpus/revocation roots and fresh environment; atomically compare-and-consume; fail closed on race/state/error; cache key binds complete invocation/context without secrets, never crosses tenant/context, uses short positive TTL and no unsafe negative/unknown reuse absent proved monotonicity; fake dispatch runs zero times on rejection and once on success; post-dispatch observation remains separate.

## LIG-037 Harden agent-supervisor pre-dispatch integration

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: integration
- Depends on: LIG-017, LIG-034, LIG-035
- Goal id: LIG-G110
- Outputs: ipfs_accelerate_py/agent_supervisor/admissibility_enforcement.py, test/api/test_agent_supervisor_admissibility_enforcement.py
- Validation: python -m pytest test/api/test_agent_supervisor_admissibility_enforcement.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/supervisor-integration
- Parallel lane: lig-supervisor-enforcement
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 11000
- Predicted files: ipfs_accelerate_py/agent_supervisor/admissibility_enforcement.py, test/api/test_agent_supervisor_admissibility_enforcement.py
- Interfaces: SupervisorPreInvocationEnforcement@1
- Allow concurrent with: LIG-036, LIG-038
- Conflict policy: Add a thin accelerate-side enforcement leaf/test after the base bridge; call datasets service/receipt contracts lazily, do not duplicate gate logic, edit the protected LIG docs, widen registry changes, touch datasets formalization, or invoke real tools.
- Preconditions: Base supervisor bridge, authorization service, and receipt contracts pass; use a matching accelerate branch/worktree if the submodule requires it.
- Effects: Supervisor plans and tool proposals can be evaluated and exact allow receipts revalidated before the supervisor delegates a side effect.
- Evidence subset: lazy import, pinned-root load, non-allow rejection, exact-context mutation, no-call, and one-call supervisor receipt
- Acceptance: Import agent_supervisor without datasets/heavy prover side effects; use explicit off/audit/shadow/enforce mode and injected store/service; bind supervisor actor/delegation/audience/task/plan/tool/arguments/effects/environment; reject abstain/reject/error/expired/replayed/root-changed/environment-changed receipts; call fake delegate once only after atomic consumption; emit decision/runtime observation without treating it as theorem proof.

## LIG-038 Harden Python and MCP authorization APIs

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: integration
- Depends on: LIG-018, LIG-034, LIG-035
- Goal id: LIG-G110
- Outputs: ipfs_datasets_py/logic/admissibility/api.py, ipfs_datasets_py/mcp_server/tools/logic_admissibility_enforcement.py, tests/unit/logic/admissibility/test_api.py, tests/unit/mcp_server/test_logic_admissibility_enforcement.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_api.py tests/unit/mcp_server/test_logic_admissibility_enforcement.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/supervisor-integration
- Parallel lane: lig-mcp-api-enforcement
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 11000
- Predicted files: ipfs_datasets_py/logic/admissibility/api.py, ipfs_datasets_py/mcp_server/tools/logic_admissibility_enforcement.py, tests/unit/logic/admissibility/test_api.py, tests/unit/mcp_server/test_logic_admissibility_enforcement.py
- Interfaces: IntentAuthorizationAPI@1, MCPIntentAuthorization@1
- Allow concurrent with: LIG-036, LIG-037
- Conflict policy: Add API/enforcement wrappers after the base MCP tool module; do not rewrite it, register shared exports/tools, invoke a real MCP tool, require network/models/optional solvers, edit service/runtime/supervisor, or touch registry.
- Preconditions: Base MCP normalize/formalize/query/check tools, authorization service, and receipts pass.
- Effects: Python and MCP callers can evaluate exact invocations and verify receipts through stable redacted schemas while evaluation remains distinct from tool execution.
- Evidence subset: API/MCP schema, redaction, compatibility, malformed input, backend unavailable, and no-invocation receipt
- Acceptance: Require explicit source/actor/audience/tool/argument/environment and exact policy/corpus/revocation roots; return allow/reject/abstain compatibility plus typed decision/receipt refs; bound and redact views; never expose prompts/arguments/secrets/witnesses/private formulas; unknown/malformed/backend-unavailable paths fail closed; tool handlers never execute targets and cannot issue/consume a dispatch capability themselves.

## LIG-039 Add redacted telemetry and staged rollout policy

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: quality
- Depends on: LIG-014, LIG-033
- Goal id: LIG-G120
- Outputs: ipfs_datasets_py/logic/admissibility/telemetry.py, config/intent_authorization_rollout.json, tests/unit/logic/admissibility/test_telemetry.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_telemetry.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-release
- Parallel lane: lig-auth-telemetry
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 8500
- Predicted files: ipfs_datasets_py/logic/admissibility/telemetry.py, config/intent_authorization_rollout.json, tests/unit/logic/admissibility/test_telemetry.py
- Interfaces: AuthorizationTelemetry@1, AuthorizationRolloutPolicy@1
- Allow concurrent with: LIG-034, LIG-040
- Conflict policy: Own telemetry leaf/new config/test; do not edit existing configs, gate/service/runtime/receipt, external dashboards, runbook, shared exports, or registry.
- Preconditions: Stable profiles/reasons and composed decision result contracts pass.
- Effects: Operators can observe query/proof/decision quality and move through off/audit/shadow/deny-canary/allow-token-canary/enforce under explicit gates without leaking private content.
- Evidence subset: bounded-label redaction, transition validation, canary scope, immediate disable, and evidence-preserving rollback receipt
- Acceptance: Metrics cover bounded source/outcome/policy/authority, latency, candidate/filter/cache classes, stale/revoked/tampered/simulation rejection, backend timeout/disagreement, review adjudication and receipt replay/expiry/TOCTOU without raw prompt/argument/formula/witness/secret/CID labels; config defaults off/audit, rejects skipped transitions, requires allowlisted reversible effects and approvals, and supports immediate receipt-consumption disable.

## LIG-040 Build the attested-authorization golden and adversarial corpus

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: quality
- Depends on: LIG-006, LIG-016, LIG-022, LIG-023, LIG-029, LIG-033
- Goal id: LIG-G120
- Outputs: tests/fixtures/logic/attested_authorization/manifest.json, tests/fixtures/logic/attested_authorization/cases.json, tests/unit/logic/admissibility/test_attested_golden_contract.py
- Validation: python -m pytest tests/unit/logic/admissibility/test_attested_golden_contract.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-release
- Parallel lane: lig-auth-fixtures
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 12000
- Predicted files: tests/fixtures/logic/attested_authorization/manifest.json, tests/fixtures/logic/attested_authorization/cases.json, tests/unit/logic/admissibility/test_attested_golden_contract.py
- Interfaces: AttestedAuthorizationGoldenCorpus@1
- Allow concurrent with: LIG-034, LIG-039
- Conflict policy: Own only the new synthetic fixture tree/manifest/structural test; do not implement production logic, change existing fixtures, ingest live/private data, weaken expected outcomes, add exports, or touch registry.
- Preconditions: Base integration and invocation/constraint/proof-authority/decision contracts are frozen.
- Effects: Every hardening stage has reviewable expected compatibility/internal outcomes, obligations and integrity failures without network, private data or optional solver dependence.
- Evidence subset: golden coverage, canonical manifest, licensing/privacy, relevant/irrelevant mutation, and non-execution receipt
- Acceptance: Cover skill/prompt/MCP equivalents; explicit allow/deny/conditional/exception/ambiguous/conflicting/missing/expired/superseded/revoked authorities; capability/trust-zone/data-egress/filesystem/network/subprocess/destructive/rollback cases; poisoned neighbors, tamper, wrong root/tenant/audience/tool/arguments/time/environment, cache substitution, malformed/real/simulated ZKP, circuit/VK/public-input mismatch, replay/race/exhaustion; bind expected filters/obligations/outcomes and source/license/privacy metadata.

## LIG-041 Integrate exports, conformance, operations, and release gates

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: quality
- Depends on: LIG-019, LIG-020, LIG-030, LIG-031, LIG-032, LIG-033, LIG-034, LIG-035, LIG-036, LIG-037, LIG-038, LIG-039, LIG-040
- Goal id: LIG-G120
- Outputs: ipfs_datasets_py/logic/admissibility/__init__.py, ipfs_datasets_py/logic/proof_corpus/__init__.py, ipfs_datasets_py/logic/intent_ir/invocation/__init__.py, ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_attested_intent_authorization.py, docs/guides/ATTESTED_INTENT_AUTHORIZATION.md, docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
- Validation: python -m pytest tests/unit/logic/admissibility/test_attested_golden_contract.py tests/integration/logic/test_attested_intent_authorization.py tests/integration/logic/test_intent_admissibility_gate.py tests/integration/logic/test_ir_family_conformance.py tests/integration/logic/test_ir_compatibility_exports.py -q
- Board namespace: logic-intent-legal-gate-v1
- Bundle: lig/authorization-release
- Parallel lane: lig-auth-release
- Resource class: cpu-validation
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/logic/admissibility/__init__.py, ipfs_datasets_py/logic/proof_corpus/__init__.py, ipfs_datasets_py/logic/intent_ir/invocation/__init__.py, ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_attested_intent_authorization.py, docs/guides/ATTESTED_INTENT_AUTHORIZATION.md, docs/implementation/runbooks/logic_intent_legal_gate_rollout.md
- Interfaces: AttestedAuthorizationConformance@1, AttestedAuthorizationRollout@1
- Allow concurrent with:
- Conflict policy: Sole datasets owner for final authorization package exports/registry and release integration; integrate only stable reviewed leaves, preserve all Legal/Security/Intent and allow/reject/abstain compatibility, and do not weaken tests, delete shims/artifacts, enable enforcement by default, edit protected architecture heaps, or commit generated/private evidence.
- Preconditions: Base benchmark/runbook and every authority/applicability/decision/runtime/bridge/telemetry/fixture continuation task pass.
- Effects: Stable APIs become discoverable and one current-tree gate validates source kinds, domains, proof/ZK/corpus/cache/runtime boundaries, deterministic replay, operations, promotion and rollback.
- Evidence subset: complete attested-authorization conformance, compatibility, promotion, incident-disable, and rollback receipt
- Acceptance: Export dependency-light symbols without import work/cycles; offline skill/prompt/MCP fixtures reach exact decisions without execution; run golden/adversarial/metamorphic/differential/native-ZK/cache-revocation/tenant-privacy/race-TOCTOU/chaos/rebuild/legacy-compatibility tests; simulated ZKP never authorizes production; document corpus/circuit/VK/policy promotion, human/legal/security review, privacy/retention, incidents, disable, shadow/deny/allow canary thresholds and rollback drill; bind release evidence to exact code, roots, keys, config, capabilities, selected tests, gaps and approvals.
