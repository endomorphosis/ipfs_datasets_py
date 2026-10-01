# Legal and UI qualifier coverage

This release extends explicitly interpreted Legal conditions and UI confirmation
policies. It does not infer missing meanings from opaque prose. The default
uninterpreted Legal/UI rows remain blocked, and neither supplied interpretations
nor a successful library build establishes source fidelity or admission.

## Entry points

Use the following versioned modules together under `ipfs_datasets_py`:

| Purpose | Module | Entry point |
| --- | --- | --- |
| Legal interpretation declaration | `logic.formalization.autoencoder.native_legal_qualified_lean` | `LegalQualifierInterpretation` |
| UI confirmation declaration | `logic.formalization.autoencoder.native_ui_confirmation_lean` | `UIConfirmationInterpretation` |
| Prepare source-bound targets | `logic.formalization.autoencoder.family_training_v7` | `prepare_family_training_targets_v7` |
| Replay inputs and build the native library | `logic.formalization.autoencoder.native_family_lake_v5` | `build_native_family_lake` |
| Validate every projection and the complete policy | `logic.formalization.autoencoder.projection_validation_contract_v5` | `validate_projection_report`, `evaluate_projection_training_batch` |
| Train and infer through live gates | `optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v5` | `train_validated_family_projection_autoencoder`, `infer_validated_family_projection_autoencoder` |

Older versioned paths remain available. The numerical trainer still fits the
auxiliary structural projection autoencoder. It does not train or replace either
the historical 8D linguistic decoder or the 384D source/formula decoder.

First prepare the exact source inputs with
`family_training_v6.prepare_family_training_targets_v6`. Build immutable
declarations against those original projection IDs, whole-source references,
source digests, payload digests and the complete ordered formula digest list.
Pass them to v7 as `legal_qualifier_inputs` or `ui_confirmation_inputs` and keep
the same original source inputs and declaration objects for the Lake call.
Declarations bind an entire original partition; no condition, exception or
formula can be omitted. The report retains the replaced rows under
`superseded_v7_qualifier_observations`.

`optimizers.logic_theorem_optimizer.authored_legal_ui_qualifier_panel.prepare_case`
contains complete, runnable source and declaration examples. It accepts exactly
three authored cases for each domain, not arbitrary input text. The smoke script
below demonstrates the full handoff to training and inference.

## Legal semantics

An `activation_guarded_legal_rule` explicitly declares:

- Every non-temporal condition as an expression built from typed atoms, `not`,
  `all`, and `any`. All conditions are tested at the evaluation origin, outside
  the modal body.
- Every exception, including its original index and exact source text, as an
  expression in the same bounded grammar.
- An optional exact duration condition with its original index, quantity,
  day/hour unit, discrete natural-number clock, evaluation origin and closed
  interval boundaries.
- Either `activation_time_waiver`, which suppresses activation when an exception
  holds at the origin, or `per_tick_exemption`, which exempts particular ticks
  inside a universal minimum-duration body.

Untimed deontic bodies, conditional deadlines, and conditional minimum durations
are supported. Deontic obligation, permission and prohibition remain distinct
operators outside their declared bodies. Temporal eventually/always must agree
with within/minimum duration respectively. No distribution of a modality over a
time interval is inferred.

Per-tick exemption cannot extend a deadline, stop a clock, or invent a suspension
duration. It is rejected for existential deadline bodies. An exact duration
literal cannot be hidden as an activation atom. The same qualifier literal
cannot map to conflicting expressions across the deontic and temporal
partitions. Business days, calendar dates, open boundaries, arbitrary metadata
and unsupported expressions remain outside this profile.

For example, a declared emergency only at tick 5 may exempt that tick of a
minimum-duration body while leaving the other ticks required. It does not waive
the complete interval. A separately declared activation-time waiver can have a
different result; the tests distinguish both interpretations.

## UI confirmation semantics

`UI_request_token_confirmation_policy` declares a finite observed event prefix.
Each event has a kind (`confirm`, `invoke`, `cancel`), action, request, token and
natural-number clock tick. The policy checks each invocation against:

- A strictly earlier confirmation in sequence order with the same action,
  request and token.
- An inclusive maximum age in the caller's declared clock ticks.
- No matching cancellation after that confirmation and before the invocation.
- No earlier invocation consuming that request/token key in the evaluation
  window. Reconfirmation cannot revive a key already consumed in that window.

Distinct events at the same clock tick retain their sequence order. A later
confirmation can clear a cancellation, but cannot clear prior consumption.
Obligation and prohibition occurrences for the same action must use consistent
policy parameters. Clock monotonicity and a valid origin are explicit conjuncts
of `uiConfirmationCheckedFormula_*`; they are not assumed true by compiling a
definition.

The origin is a sequence position. Earlier history is excluded, so this does
not prove lifetime token uniqueness. An empty observed prefix has no violating
invocations; it establishes neither execution nor successful completion. Event
authenticity, infinite future behavior, consent and backend authorization remain
unverified. These declarations do not install a runtime enforcement mechanism.

The training path checks the original native bindings, not only their flattened
`before` strings. Its supported subset requires high-risk, single-confirm
bindings and accounts for every action ID. Consent, double-confirmation,
destructive-risk and other binding policies are rejected by this new profile;
the existing routes retain their prior behavior. In particular, a weak native
permission cannot be silently upgraded to a confirmation requirement.

## Gates and coverage accounting

All 40 catalog families remain in the applicability inventory. Every active
projection must pass native syntax/lowering checks and a live, source-bound
`lake build <Lib>`. Required TLA projections also run SANY. The fixed modality
floors remain unchanged. Caller-supplied qualifier interpretations are explicitly
ineligible for floor credit; independently supplied named-formula evidence must
still meet its own requirements.

Archived JSON, old-version handles, copied declarations in a report, and a
partial successful build cannot reopen the gate. Every emitted projection must
contribute a numerical loss. Missing original declarations preserve the old
blockers rather than borrowing embedded report contents.

Use the canonical checkout or an exact reviewed export with its own Git root
and an explicit `PYTHONPATH`. Do not import the HACC editable tree first.

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/check_native_projection_lake_v5.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/default-qualifier-matrix-new

PYTHONPATH="$PWD" python scripts/ops/autoencoder/smoke_legal_ui_qualifier_training.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/legal-ui-qualifier-training-new
```

Both output directories must be fresh. The first command checks the unchanged
default matrix across all four modalities. The second checks three sources per
Legal/UI domain, trains on two, uses one for tuning, and runs gated inference.
Eight named formula families are explicitly supplied for each source. They are
not inferred translations or independent corpus holdouts. The runners download
no tools or weights and import no Mathlib. Admission/source-fidelity flags remain
false, and the Constitution remains unformalized.

## Results from the frozen 2026-10-01 candidate

All **128 focused tests passed**, with no skips: 44 Legal semantics/binding tests,
40 UI semantics/binding tests, and 44 source-replay/integration tests. The gate
control tests use explicitly labeled process doubles; those do not count as
native execution evidence. Separate real Lake tests check concrete interpreted
examples and reject false compliance, stale confirmation, cancellation,
wrong-request, token-reuse and invalid-clock claims.
Integration builds and UI semantic tests used installed Lean 4.30.0; the
supplemental Legal semantic tests used installed Lean 4.34.1. The manifest records
both tool paths and executable hashes, including packaging-time hashes for the
supplemental Legal tools.

The broader Legal/UI smoke passed **81/81 projection occurrences** across six
sources: 11 projections for each Legal source and 16 for each UI source. It ran
six actual modality Lake builds and three SANY checks. Both domains passed the
training and tuning gates, completed two optimizer steps, and ran gated inference
with a loss for every active projection. Total wall time was **43.014 seconds**.

| Domain | Native preparation/checks | Numerical preparation | Optimization | Whole smoke | Tuning objective before → selected |
| --- | ---: | ---: | ---: | ---: | --- |
| Legal | 13.678 s | 2.580 s | 0.217 s | 21.421 s | 0.001334769262 → 0.001333891695 |
| UI/UX | 13.812 s | 2.377 s | 0.013 s | 21.586 s | 0.000672470941 → unchanged |

Other time includes gate verification, calibration, checkpoint serialization
and inference. Legal's small selected improvement came from deontic/temporal
decoder calibration. Neither domain selected either Adam epoch. These authored
tuning results establish integration; they do not establish independent holdout
improvement, convergence, or better 8D/384D source reconstruction.

The separate default regression retained **63/66** supported projection checks:
Intent 23/23, Security 16/16, UI 15/16, Legal 9/11. It executed actual builds for
all four libraries, passed all 32 supplied named-formula cases and three SANY
checks, and preserved the three default Legal/UI blockers. Its complete default
training panels remain blocked by their existing missing reviews, floors or
opaque qualifiers. Expanded explicitly interpreted coverage is not a claim that
the default unsupported inputs became understood.

Native workspaces were fresh. Tests and matrix processes ran concurrently on a
shared host, so these are integration wall times, not a legal-span or bridge-on
autoencoder speed comparison. No bridge-on evaluate was measured in this release.
Only new auxiliary smoke checkpoints were written.

The [evidence manifest](../implementation/reports/evidence/native-legal-ui-coverage-20261001/manifest.json)
binds exact source snapshots, native declarations, tool output, test results and
retained failed attempts. [Results](../implementation/reports/evidence/native-legal-ui-coverage-20261001/results.json)
provide the measurements and authority boundaries in machine-readable form.
