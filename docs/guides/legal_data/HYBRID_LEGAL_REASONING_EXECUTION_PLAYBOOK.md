# Hybrid Legal Reasoning Execution Playbook

This playbook translates the improvement plan into day-to-day execution rules for implementation teams.

Related docs:
- `HYBRID_LEGAL_REASONING_IMPROVEMENT_PLAN.md`
- `HYBRID_LEGAL_REASONING_TODO.md`

## 1) Workstream Model

Run parallel workstreams with explicit handoff contracts.

WS1: IR and CNL Contracts
- Owns schema versions, grammar versions, and canonical ID policy.

WS2: Parsing and Normalization
- Owns NL/CNL parse determinism and canonical role/temporal normalization.

WS3: Compilers and Logic Emission
- Owns DCEC and Temporal Deontic FOL compilers plus parity checks.

WS4: Proof and Explainability
- Owns proof object schema, replay stability, and NL explanation rendering.

WS5: Optimizers and KG/Provers
- Owns optimizer guards, KG enrichers, and theorem prover adapters.

WS6: Query APIs and Integration
- Owns `check_compliance`, `find_violations`, `explain_proof` behavior and API contracts.

## 2) Entry and Exit Contracts Per Workstream

WS1 entry:
- Existing IR dataclass model and CNL templates are documented.

WS1 exit:
- Version-locked validators in code and test fixtures for compatibility.

WS2 entry:
- WS1 versions frozen.

WS2 exit:
- Deterministic parse metrics and canonical ID stability tests pass.

WS3 entry:
- WS2 normalized IR available.

WS3 exit:
- Formula outputs are traceable to IR IDs and source provenance.

WS4 entry:
- WS3 formula references stable.

WS4 exit:
- Proof replay deterministic and explainability outputs verified.

WS5 entry:
- WS3 baseline outputs available.

WS5 exit:
- Optimization gains achieved without semantic floor regressions.

WS6 entry:
- WS4 proof format and WS3 compilers stable.

WS6 exit:
- API contract tests green for 8-query matrix.

## 3) Weekly Execution Loop

Monday:
- Select 3-6 TODO items from `Now` bucket.
- Tag each with owner and acceptance test.

Tuesday-Thursday:
- Implement item + tests + docs in the same branch.
- Record notable decisions in decision log.

Friday:
- Run validation suite.
- Update TODO statuses (`[ ]`, `[-]`, `[x]`, `[!]`).
- Publish one-page sprint summary.

## 4) Decision Log Template

Use this template in PR descriptions or team notes.

```text
Decision ID: D-YYYYMMDD-<short-name>
Context:
Options considered:
Chosen option:
Rationale:
Trade-offs:
Rollback plan:
Affected modules:
```

## 5) Validation Suite (Minimum Required)

Contract checks:
- IR/CNL version validators.
- Backward-compat fixture load checks.

Parser checks:
- Deterministic replay checks.
- Ambiguity ranking consistency checks.

Compiler checks:
- DCEC and TDFOL parity fixtures.
- Formula->IR->source traceability checks.

Proof checks:
- Stable proof ID replay.
- Explanation contains required references.

API checks:
- 8-query matrix expected status and proof fields.

## 6) KPI Dashboard Definition

Track and review weekly:
- Parse determinism (% deterministic CNL parses).
- Canonical ID stability (% stable IDs across re-runs).
- Formula traceability (% formulas with IR + source refs).
- Proof replay stability (% deterministic proof IDs).
- Compliance API pass rate (% expected outcomes on gold tests).
- Optimization safety (semantic floor regressions count).
- Latency (`p50`, `p95`) for query and explanation APIs.

## 7) Risk Triggers and Automatic Actions

Trigger: Parse determinism < 95%
- Action: Freeze parser feature additions; run ambiguity triage.

Trigger: Any semantic floor regression on release branch
- Action: disable newest optimizer stage and revert acceptance threshold change.

Trigger: Proof replay non-determinism > 0%
- Action: lock hash policy version and investigate unstable fields.

Trigger: DCEC/TDFOL parity failures increase sprint-over-sprint
- Action: run differential diagnostics and block API rollout changes.

## 8) Release Readiness Checklist

Before canary:
- [ ] All `Now` bucket items complete for current milestone.
- [ ] Validation suite green.
- [ ] No unresolved `[!]` blockers for release scope.
- [ ] Rollback toggles documented for optimizer/KG/prover paths.

Before GA:
- [ ] Two consecutive canary windows pass quality gates.
- [ ] SLOs meet targets.
- [ ] On-call runbook updated and reviewed.
- [ ] API schema and proof schema published.

## 9) Roles and Accountability

- Architecture owner: approves schema/grammar/proof format changes.
- Compiler owner: approves logic emission changes.
- Reasoner owner: approves query behavior changes.
- Quality owner: approves gates and benchmark thresholds.
- Release owner: approves canary and GA promotion.

## 10) Working Agreements

1. No behavior change without tests.
2. No schema change without version bump or migration note.
3. No optimizer rollout without semantic guard metrics.
4. No proof format change without replay compatibility strategy.
5. Keep root workspace wrappers as thin delegates only.

## 11) Performance Baseline Snapshot

Use a stable fixture corpus and emit JSON stage timings for parse/compile/reason:

```bash
PYTHONPATH=src:ipfs_datasets_py \
	/home/barberb/municipal_scrape_workspace/.venv/bin/python \
	ipfs_datasets_py/scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py \
	--input-jsonl ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_cli_batch_sentences.jsonl \
	--sentence-field sentence \
	--iterations 3 \
	--jurisdiction us/federal \
	--output-json /tmp/hybrid_v2_perf_baseline.json \
	--pretty
```

Expected artifact:
- `/tmp/hybrid_v2_perf_baseline.json`

Artifact sections:
- `metadata`: run timestamp, platform, processor, sentence count, iterations.
- `stage_timings.parse`: `mean_ms`, `p50_ms`, `p95_ms`, min/max.
- `stage_timings.compile_dcec`: DCEC compile timings.
- `stage_timings.compile_tdfol`: TDFOL compile timings.
- `stage_timings.reason_check_compliance`: compliance reasoning timings.
- `cases`: per-sentence timing rows.

Interpretation guidance:
- Compare new baselines against last accepted baseline on the same machine class.
- Prioritize `p95_ms` over `mean_ms` for release gating.
- Treat one-off spikes as noise unless repeated over at least 3 runs.

Threshold guidance (initial):
- `parse.p95_ms` regression > 20%: investigate parser changes before merge.
- `compile_dcec.p95_ms` or `compile_tdfol.p95_ms` regression > 20%: inspect compiler path and parity fixtures.
- `reason_check_compliance.p95_ms` regression > 25%: inspect proof store, optimizer/KG/prover toggles.
- If two or more stages regress above threshold in the same PR, block promotion pending triage.
