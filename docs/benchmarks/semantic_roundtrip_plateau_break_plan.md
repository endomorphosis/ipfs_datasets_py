# Semantic Round-Trip Plateau-Break Plan

**Status:** ready for agent-supervisor handoff  
**Board:** `docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md`  
**Objectives:** `docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md`  
**Task prefix:** `## PLAT-`  
**Namespace:** `semantic-roundtrip-plateau-break-v1`

## Why this plan exists

The original research flow was:

```text
text → spaCy → autoencoder → IR → text
  → cross-entropy + cosine similarity
  → project residuals into Codex to improve deterministic text → IR
```

Later additions (Leanstral, SyMAI, Hammer/cvc5/Lean, selective repair) were hard to
compose fairly. The EVAL-001…009 harness repair fixed measurement. Fair results
show:

| Finding | Implication |
| --- | --- |
| Det. plateau e2e ≈ **0.088** (forward ≈ 0.085) | Almost all residual is **constructor/forward**, not decompile cycle |
| No optional method earned production composition | Do not swap production runtime to spaCy/AE/LLM |
| Guided AE still `not_measured` | AE teacher blocked until causal L1 adapter |
| Selective repair works on fixtures; pilots `not_triggered` | Triggers must align to real residuals |
| Hammer/cvc5/Lean = admission only | Provers filter and mint obligations; they do not lower loss alone |

**Objective of this program:** improve **typed_deontic → IR → deterministic
realizer** past 0.088 by using optional methods + provers + agent supervisor as
a **Codex improvement loop**, not as a new production mega-pipeline.

## Doctrine (one diagram)

```text
Teachers (offline)
  spaCy diagnostics
  AE residuals (after adapter)
  Leanstral (± SyMAI) selective IR patches
        │
        ▼
Provers (deterministic)
  Hammer / cvc5 / Lean
  admit | reject | timeout/error fail-closed
  proof_obligation IDs for failed constraints
        │
        ▼
PlateauCodexPacket@1
  baseline L1, residual facets, admitted ΔL1,
  rejected proposals, predicted files, validation cmds
        │
        ▼
ipfs_accelerate_py agent supervisor
  lease → Grok/Codex edits deterministic compiler/decompiler only
  re-run structural admit + unit tests + pilot re-score
        │
        ▼
Production remains det. path until bootstrap CI high < 0 vs 0.088
```

## Goal / subgoal tree

| ID | Goal | Priority | Parallel lane family |
| --- | --- | --- | --- |
| **PLAT-G000** | Break det. plateau with prover-gated Codex loop | P0 | root |
| **PLAT-G010** | Residual forensics catalog | P0 | residual |
| **PLAT-G020** | Prover-gated Codex packet contract | P0 | packets |
| **PLAT-G030** | Pilot residual → selective-repair triggers | P0 | triggers |
| **PLAT-G040** | Leanstral proposal teacher | P1 | leanstral-teacher |
| **PLAT-G050** | spaCy diagnostic teacher | P1 | spacy-teacher |
| **PLAT-G060** | Causal AE L1 adapter | P2 | autoencoder |
| **PLAT-G070** | Supervisor materializer / launch | P0 | supervisor |
| **PLAT-G080** | Det. compiler edit waves | P0 | det-* case lanes |
| **PLAT-G090** | Re-measure + promotion decision | P0 | remeasure |
| **PLAT-G100** | Dual CE/cosine + structural metrics | P2 | metrics |

## Executable tasks (parallelizable)

| Task | Depends on | Lane | Purpose |
| --- | --- | --- | --- |
| PLAT-000 | — | plat-docs | Seal plan artifacts |
| PLAT-010 | 000 | plat-residual | Residual catalog |
| PLAT-020 | 000 | plat-packets | Packet contract |
| PLAT-030 | 010 | plat-triggers | Trigger map |
| PLAT-040 | 020, 030 | plat-leanstral-teacher | LLM proposals + admission |
| PLAT-050 | 000 | plat-spacy-teacher | spaCy diagnostics |
| PLAT-060 | 000 | plat-autoencoder | Causal AE adapter |
| PLAT-070 | 020 | plat-supervisor | Materialize packets → supervisor tasks |
| PLAT-080 | 000 | plat-metrics | Dual metrics bridge |
| PLAT-081 | 010, 020, 070 | plat-det-legal-doc | Edit wave legal_doc_1 |
| PLAT-082 | 010, 020, 070 | plat-det-construction | Edit wave construction_contract |
| PLAT-083 | 010, 020, 070 | plat-det-corp-policy | Edit wave corp_policy_1 |
| PLAT-084 | 010, 020, 070 | plat-det-exec-order | Edit wave exec_order_1 |
| PLAT-090 | 081–083 | plat-remeasure | Bootstrap re-score + decision |
| PLAT-091 | 090 | plat-remeasure | Optional full matrix (only if plateau moved) |

### Waves

1. **Foundation (max parallel):** 010, 020, 050, 060, 070, 080  
2. **Teachers:** 030 → 040  
3. **Edits (case-parallel):** 081–084  
4. **Close:** 090 → (optional) 091  

## How provers improve Codex packets

Structural constraints (declared):

- `non_vacuous_candidate`
- `rule_cardinality_preserved`
- `untriggered_projection_preserved`

| Prover result | Packet effect |
| --- | --- |
| Accept | `implementable=true`, field change list, tool receipts |
| Reject | `implementable=false`, `validator_reject`, constraint detail → obligation for det. code |
| Timeout / error | Fail-closed; same as non-implementable for edit authority |

Agent supervisor merges **only** when validation re-runs structural checks +
pytest + pilot re-score. Proof pass never counts as lower e2e by itself.

## Role of each method (runtime vs teacher)

| Method | Runtime production? | Role in this plan |
| --- | --- | --- |
| typed_deontic + det. realizer | **Yes (default)** | Improvement target |
| spaCy | No | Diagnostic teacher (PLAT-050) |
| Autoencoder | No until adapter + promotion | Teacher residuals (PLAT-060, 080) |
| Leanstral | No (not default realizer) | Selective patch proposer (PLAT-040) |
| SyMAI | No | Optional tool scaffold around Leanstral |
| Selective repair | Optional research | Triggered teacher path (PLAT-030/040) |
| Hammer/cvc5/Lean | Gate only | Admission + obligations (PLAT-020/040/07x/08x) |

## Success criteria

| Level | Criterion |
| --- | --- |
| Packet loop live | Residual CID + packet tests + materializer emit tasks |
| Plateau moved | Pilot det. mean e2e **&lt; 0.088** and bootstrap **CI high &lt; 0** |
| Promotion | Full gates + decision receipt; replacement report untouched |
| Partial success | No e2e win but obligation-driven edit waves improve facet residuals and packet loop is operational |

## Related sealed evidence

- `docs/benchmarks/semantic_roundtrip_eval_repair_results.md`
- `docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md`
- `docs/performance_snapshots/2026-07-27_semantic_roundtrip_eval_repair_matrix.json`
- `docs/benchmarks/semantic_roundtrip_canonical_compiler_decision.md`

## Non-goals

- Replacing the EVAL harness board
- Always-on LLM production path
- Full 670-matrix re-run before residual-driven det. edits
- Gold-leaking AE “guidance”
