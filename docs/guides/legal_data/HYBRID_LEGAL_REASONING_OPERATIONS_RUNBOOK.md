# Hybrid Legal Reasoning Operations Runbook

This runbook describes how to operate rollout controls and gates for hybrid legal reasoning.

Related scripts:
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_ga_gate.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_optimizer_benchmark.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh`
- `ipfs_datasets_py/scripts/ops/legal_data/build_shadow_mode_audit.py`
- `ipfs_datasets_py/scripts/ops/legal_data/select_formal_logic_canary_mode.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_ga_gate.py`
- `ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_optimizer_benchmark.py`
- `ipfs_datasets_py/scripts/ops/legal_data/export_proof_certificates_audit.py`

## 1) Rollout Modes

### Shadow mode
Purpose:
- Run baseline and hybrid in parallel and compare outputs.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json`

Interpretation:
- `summary.shadow_ready=true` means audit checks passed.
- `summary.failure_count>0` means not ready for canary/GA promotion.

### Canary mode
Purpose:
- Route low-risk traffic to hybrid only when policy permits.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/canary_mode_decision.json`

Interpretation:
- `route=hybrid` and `hybrid_enabled=true` means hybrid route selected.
- `proof_audit_required=true` means proof audit sampling must run.

### GA gate mode
Purpose:
- Evaluate quality/safety/latency thresholds prior to GA.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_ga_gate.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/ga_gate_assessment.json`

Interpretation:
- `summary.ga_ready=true` means GA gate passed.
- failing checks list exactly which thresholds blocked promotion.

### Optimizer benchmark mode
Purpose:
- Compare quality/safety metrics with optimizers disabled vs enabled.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_optimizer_benchmark.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/optimizer_onoff_benchmark.json`

Interpretation:
- `summary.improvement_count` and `summary.regression_count` summarize directional wins/losses.
- `summary.net_score` is `improvements - regressions` across tracked metrics.

### Proof certificate audit mode
Purpose:
- Export normalized proof-certificate and certificate-to-IR trace-map artifacts for audit/review.

Command:
```bash
bash ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh
```

Primary artifact:
- `artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json`

Interpretation:
- `summary.duplicate_certificate_id_count=0` indicates no certificate ID collisions in the store.
- `summary.missing_trace_map_count=0` indicates all exported certificates map to at least one IR reference.

## 2) Required Environment Toggles

Shared toggles:
- `LIMIT_SEGMENTS` (default `50`)

Canary toggles:
- `RISK_LEVEL=low|medium|high`
- `REQUIRE_SHADOW_READY=1|0`
- `RUN_SHADOW_FIRST=1|0`

GA toggles:
- `RUN_CANARY_FIRST=1|0`
- `RUNTIME_STATS_PATH=<path>` (optional; if omitted, latency checks may be skipped by policy)
- `GA_GATE_OUTPUT_PATH=<path>`

Core conversion toggles (from regression runner):
- `ENABLE_HYBRID_IR=0|1`
- `HYBRID_IR_JURISDICTION_FALLBACK=<value>`
- `HYBRID_IR_CANONICAL_PREDICATES=1|0`
- `ALLOW_SOURCE_CONDITIONED_ROUNDTRIP=1|0`
- `ENABLE_LLM_DECODER_PASS=1|0`

Proof certificate audit toggles:
- `PROOF_STORE_PATH=<path>`
- `PROOF_CERT_AUDIT_PATH=<path>`

## 3) Promotion Procedure

Step 1:
- Run shadow mode and inspect `shadow_mode_audit.json`.

Step 2:
- Run canary mode with `RISK_LEVEL=low` and confirm route decision plus proof-audit requirement.

Step 3:
- Run GA gate assessment and inspect failures.

Promotion rule:
- Promote only when:
  - shadow is ready,
  - canary enables hybrid under target risk profile,
  - GA gate reports `ga_ready=true`.

## 4) Failure Triage

When shadow fails:
- Inspect `checks` entries in `shadow_mode_audit.json`.
- Typical issue: quality floor miss (for example enumeration integrity).

When canary routes to baseline unexpectedly:
- Inspect `reason` in `canary_mode_decision.json`.
- Confirm risk level and shadow readiness policy settings.

When GA gate fails:
- Inspect failed `checks` in `ga_gate_assessment.json`.
- Address failures by category:
  - quality floor misses: adjust parser/compiler quality path
  - safety ceiling misses: reduce artifacts/orphans and blocker conditions
  - latency failures: optimize or adjust runtime SLO configuration

## 5) Incident Response and Rollback

Immediate rollback conditions:
- spike in error rate or timeout rate above thresholds
- safety blocker asserted (`theorem_ingestion_blocker=true`)
- shadow/canary divergence with unexplained semantic regression

Rollback actions:
1. Force baseline route (set canary to high risk or disable hybrid route).
2. Keep proof audits active for diagnostics.
3. Capture latest shadow/canary/GA artifacts for postmortem.
4. Re-enable hybrid only after shadow and GA checks pass.

## 6) Operator Checklist

Before rollout:
- [ ] Shadow audit generated and reviewed.
- [ ] Canary decision reviewed for target risk profile.
- [ ] GA assessment generated and reviewed.

After rollout:
- [ ] Archive artifacts for traceability.
- [ ] Record promotion/rollback decision and reason.
- [ ] Update TODO status and execution notes when behavior changes.
