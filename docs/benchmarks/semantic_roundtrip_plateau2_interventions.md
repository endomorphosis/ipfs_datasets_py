# Plateau2 Intervention Roles, Capabilities, and Ablations (PLAT2-035)

**Interfaces:** `Plateau2InterventionRegistry@1`, `SemanticRoundtripCapabilityRecord@1`  
**Module:** `benchmarks/semantic_roundtrip/holdout_interventions.py`  
**Task:** PLAT2-035 / PLAT2-G035  
**Evidence:** PLAT2EV035INT  
**Status:** preregistered before optional teachers and edit waves

## Purpose

PLAT2-035 freezes the **method role registry**, **exact capability identities**,
and **residual → intervention / ablation plan** so later teachers (PLAT2-040),
deterministic edit waves (PLAT2-050), and candidate freeze (PLAT2-055) share one
outcome-independent attribution plan.

This task is **classification and plan only**. It does not change production
defaults, optional adapters, sealed PLAT results, or inspect blind
inputs/outcomes.

## Doctrine

| Method | Role | Semantic authority |
| --- | --- | --- |
| Deterministic compiler / IR / decompiler | `production_edit_target` | true (via e2e gates) |
| Autoencoder | `causal_guidance_only_when_scored_supported` (only when `scored_supported`) | false |
| spaCy | `non_authoritative_diagnostics` | false |
| SyMAI | `orchestration_routing_only` (no proof credit) | false |
| Leanstral | `proposal_teacher` (direct route ≠ SyMAI route) | false |
| Hammer / cvc5 / Lean | `structural_gate` | false |

Production remains **typed_deontic → IR → deterministic realizer**. Queries,
diagnostics, tests, model outputs, and structural receipts do **not** replace
semantic e2e loss.

## Artifact paths

| Artifact | Path |
| --- | --- |
| Intervention registry module | `benchmarks/semantic_roundtrip/holdout_interventions.py` |
| Frozen registry | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json` |
| Unit tests | `tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py` |
| This document | `docs/benchmarks/semantic_roundtrip_plateau2_interventions.md` |
| Capability inventory (PLAT smoke) | `workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json` |
| AE qualification | `workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json` |
| Repair-dev residual catalog | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_residual_catalog.json` |
| Experiment baseline (PLAT2-025) | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json` |

## Method status taxonomy

Every method record carries exactly one of:

| Status | Meaning |
| --- | --- |
| `semantic_scored` | Fairly measured for the declared role (production det path) |
| `not_measured` | Never fairly measured / preflight blocked |
| `runtime_failed` | Execution attempted; runtime or provider failure |
| `terminal_unsupported` | Terminal unsupported on this path |
| `not_selected` | Available for its advisory/gate role but not production composition |

Statuses are backed by **PLAT evidence** (post-PLAT baseline, AE qualification)
or a **bounded capability smoke**. Health-only probes **cannot** establish model
inference: a route with `health_only=true` must not claim
`model_inference_established=true`.

## Exact identities (summary)

| Method | Identity anchors |
| --- | --- |
| Deterministic compiler | `TypedDeonticCanonicalConstructor@1` + `CanonicalDeterministicRealizer@1` on arm `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Autoencoder | Pinned state CID/sha256, read-only access, reviewed adapter id (currently absent) |
| spaCy | Distribution/version + `en_core_web_sm` full pipeline (no blank fallback) |
| SyMAI | `symbolicai` version, `symai_router` route, resolved Leanstral binding, `proof_credit: false` |
| Leanstral | Model/endpoint/backend/provider, `direct_openai_compatible_http` route |
| Hammer | Hammer module/version + cvc5 solver binding |
| cvc5 | Solver path/version/executable hash, bounded SMT2 smoke |
| Lean | Lean 4 toolchain path/version/executable hash, bounded smoke |

## Autoencoder guidance gate

Causal AE guidance is **eligible only** when the reviewed feature→canonical-field
adapter is `scored_supported`. The checked-in qualification remains
`unavailable_no_reviewed_causal_l1_adapter` (`not_measured` /
`terminal_unsupported`). Guided cells stay off the semantic schedule until that
adapter is preregistered and reviewed.

## Residual → intervention mapping

Each repair-development residual maps, **without outcome-dependent selection**,
to:

1. **Smallest primary intervention** on the deterministic compiler:
   - `missing_rule` / `extra_rule` → `det_compiler_missing_rule_hypothesis`
   - `field_mismatch` + `missing` → `det_compiler_field_fill_hypothesis`
   - `field_mismatch` + `contradictory` → `det_compiler_field_rewrite_hypothesis`
2. **Negative controls**
   - `nc_no_edit` — baseline arm, no compiler edit
   - `nc_withhold_optional_teacher` — same hypothesis without spaCy/Leanstral/AE advisories
3. **Optional advisories** (never edit targets; eligibility status explicit)
4. **Structural gates** (Hammer/cvc5/Lean; `semantic_authority: false`)
5. **Per-wave ablation** — treatment vs no-edit vs teacher-withheld for that residual
6. **Cumulative ablation** — all prior mappings + current vs leave-current-out

Blind residual IDs, sources, and gold are **not** accessed. The public blind
seal remains unopened with zero access receipts.

## Full matrix policy

Full Cartesian method×case matrix **reruns are not allowed by default**. An
explicit evidence-backed override must supply:

- `override_id`
- `evidence_cid`
- `justification`
- `authorizer`
- `residual_mapping_ids_in_scope`
- `experiment_id` (must match freeze)
- `registry_cid` (must match freeze)

Overrides cannot set `outcome_dependent_selection` or `blind_data_used`.

## Selection policy (frozen)

| Rule | Value |
| --- | --- |
| Primary edit method | `deterministic_compiler_ir_decompiler` |
| Blind data permitted | **false** |
| Outcome-dependent selection | **false** |
| Full matrix requires override | **true** |

## Reproduce

```bash
# Build and write the frozen registry
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_interventions \
  --output workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json

# Print-only
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_interventions --print-only

# Validation
PYTHONPATH=. python -m pytest \
  tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py \
  tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py \
  tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py -q
```

## Downstream consumers

| Task | Uses this freeze for |
| --- | --- |
| PLAT2-040 | Eligible teachers/advisories only; distinct SyMAI vs direct routes |
| PLAT2-050 | One residual-scoped deterministic hypothesis per wave + ablations |
| PLAT2-055 | Attribution across waves; candidate freeze; full-matrix override gate |

## Protocol change

Changes to roles, status taxonomy, residual mapping rules, ablation structure,
or full-matrix policy require a new registry revision and new `registry_cid`.
They must not reopen the blind seal or retune against blind outcomes.
