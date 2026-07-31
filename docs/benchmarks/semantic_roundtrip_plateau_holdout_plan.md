# Plateau Holdout Wave (PLAT2)

**Status:** ready for supervisor handoff  
**Prefix:** `## PLAT2-`  
**Namespace:** `semantic-roundtrip-plateau-holdout-v2`

## Why

PLAT-000…091 improved the deterministic path on the **five sealed pilots**
(e2e 0.088 → 0.0) using residual → teacher → structural gate → agent supervisor
→ remeasure. PLAT2 generalizes the loop without adapting to the population used
for the final out-of-sample claim:

- visible repair-development cases drive residual diagnosis and deterministic
  edits;
- a separately authored blind holdout stays outside the repository, tuning
  worktrees, prompts, packets, caches, and agent context;
- one frozen candidate receives one audited blind comparison.

## Doctrine

```text
repair-development baseline + residuals
  → role/capability registry
  → obligation-first packet
  → optional diagnostics/proposals + structural admission
  → deterministic edit waves + ablations
  → candidate/config/metric freeze
  → single-use custodian access
  → frozen baseline vs candidate on blind holdout
```

Production remains **typed_deontic → IR → deterministic realizer**. The
autoencoder is bounded causal guidance only when qualified, spaCy is
diagnostics, SyMAI is orchestration, Leanstral is a proposal teacher, and
Hammer/cvc5/Lean are structural gates. Queries, diagnostics, tests, model
outputs, and structural receipts do not replace semantic e2e loss.

Blind sources/gold remain private to an evaluator/custodian boundary. Ordinary
content digests, a public seal, and append-only access receipts are sufficient;
ZK is not part of PLAT2 without a separate private-witness threat model.

## Population and freeze boundaries

| Population | Visible before candidate freeze? | Purpose |
| --- | --- | --- |
| Sealed pilots | Yes, as immutable regression controls | Preserve historical 0.0 mean e2e |
| Repair-development | Yes | Residual analysis, packets, method selection, edits, ablations |
| Blind holdout | No | One final paired baseline/candidate decision |

The blind manifest is checked for exact, normalized, provenance, near-copy, and
prompt-example leakage. Its public seal contains counts/strata and aggregate
commitments, not per-case digests, source, labels, gold IR, or semantic hints.
After access, no code, prompt,
threshold, metric, method, or population may change and the same blind set may
not be rerun.

## Tasks

| ID | Goal |
| --- | --- |
| PLAT2-000 | Seal v2 plan artifacts |
| PLAT2-010 | Residual catalog supports typed populations and rejects premature blind access |
| PLAT2-020 | Freeze repair-development and access-controlled blind holdout |
| PLAT2-025 | Freeze baseline, metrics, failure taxonomy, token budget, and decision rules |
| PLAT2-030 | Build obligation-first repair-development packets |
| PLAT2-035 | Freeze method roles, capabilities, and ablation plan |
| PLAT2-040 | Run optional evidence-gated teachers on repair-development |
| PLAT2-050 | Run deterministic repair-development edit waves |
| PLAT2-055 | Attribute waves, freeze one candidate, and authorize holdout |
| PLAT2-060 | Execute one-shot blind comparison and publish decision |

## Relation to PLAT pilots

Pilot evidence remains historical and sealed. Holdout must not regress pilot
mean e2e 0.0 when re-scored.

PLAT/SRT already owns the composition evidence. PLAT2 consumes those receipts
to classify method roles and selects the smallest residual-specific experiment;
it does not repeat the full Cartesian matrix unless a preregistered,
evidence-backed override justifies the cost.

## Decision outcomes

- `improvement_confirmed`: paired blind candidate-minus-baseline CI high is
  below zero and every frozen gate passes.
- `generalization_confirmed_no_improvement`: the frozen noninferiority rule and
  no-regression gates pass, but no improvement is claimed.
- `promotion_declined`: all other complete outcomes.
- `incomplete`: missing, leaked, stale, underpowered, or unauthorized evidence.

A failed or diagnostically useful blind result may seed a new board only with a
newly authored blind population. It cannot tune and rerun this one.
