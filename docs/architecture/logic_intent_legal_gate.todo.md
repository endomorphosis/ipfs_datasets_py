# Logic Intent · Legal · Security Gate Task Board (unified / deduplicated)

Executable projection of
[`logic_intent_legal_gate.objectives.md`](./logic_intent_legal_gate.objectives.md).
Human plan:
[`LOGIC_INTENT_LEGAL_GATE_PLAN.md`](./LOGIC_INTENT_LEGAL_GATE_PLAN.md).

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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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

- Status: pending
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
