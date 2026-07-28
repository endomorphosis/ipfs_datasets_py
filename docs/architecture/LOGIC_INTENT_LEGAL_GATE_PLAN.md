# Logic Intent · Legal · Security Gate Plan

**Status:** active unified program plan (LIG absorbs completed IRF)  
**Date:** 2026-07-28  
**Branch:** `feature/logic-intent-legal-gate`  
**Primary repo:** `ipfs_datasets_py`  
**Companion heaps:**  
- Goals: [`logic_intent_legal_gate.objectives.md`](./logic_intent_legal_gate.objectives.md)  
- Tasks: [`logic_intent_legal_gate.todo.md`](./logic_intent_legal_gate.todo.md) (**sole active** board)  
- Deep authorization design: [`INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`](./INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md)
- Launch: [`scripts/ops/logic_intent_legal_gate/`](../../scripts/ops/logic_intent_legal_gate/)  
**Predecessor:** [`IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`](./IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md) / IRF-* board (**37/37 completed**; do not co-launch)  

## 1. Problem statement

`ipfs_datasets_py.logic` already has three IR families and substantial infrastructure:

| Family | Role today | Gap for this program |
|--------|------------|----------------------|
| **IntentIR** | SkillCenter → grounded goals/actions/effects; GraphRAG; syntactic formalizer scaffold | Production formalization must reuse Legal’s measured compile/decompile/round-trip machinery; MCP/prompt/tool sources need the same fail-closed path as skills |
| **LegalIR** | Typed deontic canonical compiler, decompiler, round-trip, corpus formalization | Proofs and receipts must be queryable at corpus scale and ZKP-attestable without re-running heavy provers |
| **SecurityIR** | Immutable security declarations, adapters, result authorities | Same: cached, attested constraint artifacts for join with intent |
| **ir_core / formalization / zkp** | Shared envelopes, claims, ZKP backends (incl. legal-theorem MVP) | Unified **proof corpus store**, cross-family query, and a single **admissibility gate** |

Downstream, `ipfs_accelerate_py.agent_supervisor` already has `IRFamily`, adapters, and constraint compilers (`intent_constraint_adapter`, `legal_constraint_adapter`, `ir_registry`). This program closes the loop:

```text
Skill | Prompt | MCP tool call
        │
        ▼  (IntentIR normalize + formalize)
  Intent formal artifact + obligations  ──CID──► proof corpus (ZKP-attested)
        │
        ▼  query attested LegalIR + SecurityIR constraints
  Admissibility gate  ──allow / reject / abstain──► supervisor / runtime
```

**Non-goals (fail-closed invariants):**

- IntentIR never authorizes or executes skill/prompt text.  
- GraphRAG / LLM / advisor outputs never become theorem proof authority.  
- Evidence gates, policy decisions, monitors, and theorem proofs remain non-substitutable.  
- ZKP receipts bind statement digests and configuration; absence of a proof is never “allow”.  
- Mutable HF revisions, unpinned bundles, or unattested cache rows fail closed.

## 2. Architecture target

### 2.1 Shared formalization spine (reuse Legal)

Lift and reuse—not fork—the Legal measured path:

- `legal_ir.canonical_contracts` / `CanonicalCompiler` / `CanonicalDecompiler` / `CanonicalRoundTrip`  
- `formalization` samples, views, compiler, source maps, obligations  
- `ir_core` identity, provenance, claims, protocols, artifacts  

Intent adapters implement the **same protocols** Legal already satisfies, with Intent-specific vocabulary (goals, modalities, action contracts, effects, verification steps) mapped into formal views and solver-neutral obligations.

Security continues to emit typed constraints (policy, resource, principal, channel) that join as **negative/positive constraints** against Intent obligations—not as free-text policy.

### 2.2 Proof corpus & ZKP attestation

Every successful (or reviewed abstention) formalization/proof run produces:

1. **Artifact envelope** (schema, producer, config digest, source CIDs, review state).  
2. **Formal artifact + obligation set** (CIDv1).  
3. **Backend attempt / result receipt** with exact `AuthorityKind`.  
4. Optional **ZKP proof + verification key registry entry** over a pinned statement circuit (reuse `logic/zkp` provekit/groth16 paths; extend beyond legal-theorem MVP).

Storage is content-addressed (local artifact store + IPFS pin when available). Indexes are secondary: family, source identity, obligation digest, jurisdiction/profile, skill/entry CID, MCP tool identity, time bounds.

### 2.3 Query surface

A single query API (Python + optional MCP tool) answers:

- **By CID:** load/verify envelope + proof + ZKP.  
- **By source:** all Intent formalizations for a skill/entry/prompt hash.  
- **By obligation:** Legal/Security constraints that apply to a given action/resource/principal slice.  
- **Join query (admissibility):** given Intent formal artifact CID (or raw IntentIR), return allow / reject / abstain with structured reasons, bound constraint CIDs, and optional ZKP verify flags.

### 2.4 Admissibility gate semantics

```text
allow    iff every required Intent action has an applicable positive grant,
           its declared non-conflict obligation is proved, all hard Security
           invariants and pre-dispatch obligations are discharged, corpus
           coverage is sufficient, and all required proof/ZKP/integrity,
           freshness, revocation, tenant, and context checks pass.

reject   iff a hard constraint forbids an Intent effect/action, or integrity fails.

abstain  iff evidence incomplete, prover unavailable, ZKP missing when required,
           or semantics unsupported — never promote to allow.
```

Profiles (examples): `dev-offline`, `security-lite`, `legal-strict`, `zkp-required`.
The compatibility wire result remains allow/reject/abstain. Internally the
deep design distinguishes deny, review, indeterminate, and error before all
non-allow outcomes map to rejection at an enforcement boundary. SAT, retrieval,
cache presence, signatures, and artifact-membership proofs are not permission.

### 2.5 Agent supervisor integration

- Register LIG artifact schemas in `ir_registry` / accelerate IR adapters.  
- Emit constraint packets consumable by `intent_constraint_adapter` / legal / security compilers.  
- Decision-runtime semantic change kinds already include intent/legal/security IR; gate results become first-class runtime observations.  
- MCP tools: `normalize_intent`, `formalize_intent`, `query_proof_corpus`, `check_intent_admissibility`.

## 3. Dependency DAG (parallel waves)

```text
Wave 0  LIG-G010 shared formalization protocols & Legal toolchain extraction
          │
          ├─► Wave 1a  LIG-G020 Intent formalization production path
          ├─► Wave 1b  LIG-G030 Legal proof cache + ZKP
          └─► Wave 1c  LIG-G040 Security proof cache + ZKP
                    │
                    ▼
          Wave 2  LIG-G050 unified proof corpus store & query
                    │
                    ▼
          Wave 3  LIG-G060 composite admissibility gate
                    │
                    ├─► Wave 4a  LIG-G070 supervisor + MCP integration
                    └─► Wave 4b  LIG-G080 eval, benchmarks, rollout
                                      │
                                      ▼
          Wave 5  LIG-G090..G120 authority, applicability, receipt,
                  enforcement, adversarial hardening (LIG-022..041)
```

Waves 1a–1c are independent file owners and should run as parallel supervisor lanes after Wave 0.

## 4. Bundle / lane ownership

| Bundle | Parallel lane | Owns (examples) |
|--------|---------------|-----------------|
| `lig/formalization-shared` | `lig-formal-shared` | shared protocols, Legal→shared extractions, tests under `tests/unit/logic/formalization` |
| `lig/intent-compile` | `lig-intent` | `logic/intent_ir/formalize/**`, skill/prompt/MCP normalizers, intent formal tests |
| `lig/legal-proof-cache` | `lig-legal-cache` | legal proof indexer, ZKP statements for legal theorems, legal cache CLI |
| `lig/security-proof-cache` | `lig-security-cache` | security proof/constraint cache, ZKP where applicable |
| `lig/proof-store` | `lig-store` | `logic/proof_corpus/**`, query API, integrity loaders |
| `lig/admissibility-gate` | `lig-gate` | join engine, profiles, adversarial gate tests |
| `lig/supervisor-integration` | `lig-supervisor` | accelerate adapters, MCP tools, decision-runtime hooks |
| `lig/eval-rollout` | `lig-eval` | fixtures, benchmarks, runbooks, shadow/canary docs |

**Conflict rule:** no task edits another bundle’s `Outputs:` without refining the heap first. Shared package `__init__.py` / registry files only change in designated integration tasks.

## 5. Branch and execution

- Prefer branch `feature/logic-intent-legal-gate` off current `main` of `ipfs_datasets_py` (and a matching accelerate branch only for LIG-G070).  
- Task prefix: **`LIG-`**. Goal prefix: **`LIG-G`**. Board namespace: `logic-intent-legal-gate-v1`.  
- Launch with agent supervisor objective-daemon + multi-lane implementation using bundle/conflict fields on the todo board.  
- Protected operator inputs: this plan, `logic_intent_legal_gate.objectives.md`, `logic_intent_legal_gate.todo.md`.

## 6. Success criteria (program)

1. A SkillCenter pilot skill → IntentIR → formal obligations is fully offline, content-addressed, and non-executing.  
2. Legal and Security constraint sets for a declared profile load by CID with ZKP verify (or explicit abstain if ZKP required and missing).  
3. Admissibility gate returns structured allow/reject/abstain for at least: one explicitly permitted intent, one legally forbidden effect, one security-denied resource, one contradictory authority, and one incomplete-evidence abstain.
4. An allow receipt binds actor, audience, tool/arguments, effects, policy/corpus/revocation roots, environment, nonce, and expiry; every non-allow outcome rejects at dispatch.
5. Supervisor/MCP can invoke the gate without importing heavy optional provers at package import time or executing source/tool content.
6. Simulated ZKP is usable only for clearly labeled development/audit fixtures and cannot authorize a production dispatch.
7. Parallel lanes complete without file ownership conflicts; all task `Validation:` lines pass on the current tree.

## 7. Relationship to IRF (merged / deduplicated)

IRF established family boundaries and Intent scaffolding and is **fully completed**
(37/37 on `ir_family_refactor_intent_ir.todo.md`). LIG **does not reopen** Security
freeze or ir_core design. It **consumes** IRF interfaces and adds only net-new work:

| Absorbed from IRF (do not reimplement) | LIG net-new |
|----------------------------------------|-------------|
| `FormalizationCompiler` Protocol + contract tests | Prompt + MCP Intent source adapters |
| Legal measured compile/decompile/round-trip | Legal proof cache + ZKP statement |
| `IntentFormalizationCompiler` | Security constraint cache |
| Security `formalization_adapter` | `proof_corpus` store/query/attest |
| SkillCenter intent path | Admissibility profiles + gate |
| | Supervisor bridge + MCP tools |
| | Benchmarks + rollout runbook |
| | Invocation-context envelope + Legal/Security applicability |
| | Authority-grade manifest/revocation/query/verification |
| | Decision receipts, one-time dispatch, TOCTOU and tenant isolation |
| | Adversarial conformance, telemetry, promotion and rollback evidence |

**Anti-contention rules:**

1. Only board namespace `logic-intent-legal-gate-v1` is live for this program.  
2. Do not start `ir-family-v1` implementation supervisors while LIG lanes run.  
3. State/worktrees: `data/agent_supervisor/logic_intent_legal_gate/` only.  
4. Residual foundation gap: Legal frozen adapter L1 CID (LIG-003) — fix integrity, do not skip.

## 8. Supervisor operation (unified multi-lane)

Run commands from the `ipfs_datasets_py` repository root on branch
`feature/logic-intent-legal-gate`. Preferred operator entry:

```bash
# Dry-run (no implementation model): inspect ready tasks
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --dry-run

# Launch 4 isolated shards (default SHARD_COUNT=4)
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh
```

Equivalent manual one-shard form (set `SHARD` to 0..3):

```bash
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/../ipfs_accelerate_py:$(pwd)"
python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor \
  --implement \
  --task-prefix "LIG-" \
  --task-shard-count 4 \
  --task-shard-index "$SHARD" \
  --todo-path docs/architecture/logic_intent_legal_gate.todo.md \
  --state-dir "data/agent_supervisor/logic_intent_legal_gate/shards/$SHARD/state" \
  --worktree-root "data/agent_supervisor/logic_intent_legal_gate/shards/$SHARD/worktrees" \
  --implementation-protected-path docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md \
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.objectives.md \
  --implementation-protected-path docs/architecture/logic_intent_legal_gate.todo.md
```

The todo board and shard task-state files are the authority for current
readiness; the initial absorption wave has already advanced. Do not run coarse
objective-generated IRG/LIG refill boards concurrently with this reviewed
board unless refill is deliberately enabled later.

## 9. Authority and enforcement gap continuation

The base LIG tasks deliberately establish a small working store/query/gate.
The companion
[`INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`](./INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md)
records the full threat model, canonical contracts, proof and ZK semantics,
cache identity, applicability rules, decision algebra, privacy, runtime
enforcement, validation, and governance requirements.

LIG-022–041 append this work without reopening completed foundation tasks:

1. canonicalize the proposed invocation and build source-specific adapters;
2. adapt Legal and Security formal artifacts through shared applicability
   contracts;
3. harden the proof corpus with exact manifests, revocation, tenant/scope
   filters, independent native/ZK verification, and legacy quarantine;
4. require explicit permission, proved non-conflict, Security invariants,
   obligations, and coverage before allow;
5. issue exact-context receipts and one-time capabilities;
6. revalidate immediately before supervisor/MCP dispatch; and
7. gate release on adversarial, privacy, cache, circuit/VK, replay, race,
   chaos, promotion, and rollback evidence.

Only `logic-intent-legal-gate-v1` is extended. The completed IRF task board
remains historical and must not receive duplicate authorization tasks.
