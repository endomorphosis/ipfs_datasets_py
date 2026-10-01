# Guarded Intent projections and training

This additive path connects the existing finite guarded Intent interpreter to
the strict native projection gate. It preserves the old producer modules,
checkpoints and default unsupported cases. It adds no inference from opaque
predicate text into program state.

## Entry points

Use these versions together:

| Purpose | Module under `ipfs_datasets_py` | Entry point |
| --- | --- | --- |
| Bind declared effects to supplied finite state predicates | `logic/formalization/autoencoder/native_intent_guarded_lean.py` | `IntentEffectBindings`, `prepare_guarded_payload` |
| Prepare complete source-bound targets | `logic/formalization/autoencoder/family_training_v6.py` | `prepare_family_training_targets_v6` |
| Prepare and execute native checks | `logic/formalization/autoencoder/native_family_lake_v4.py` | `prepare_native_family_lean`, `build_native_family_lake` |
| Enforce the complete modality policy | `logic/formalization/autoencoder/projection_validation_contract_v4.py` | `validate_projection_report`, `evaluate_projection_training_batch` |
| Train or infer with the live gate | `optimizers/logic_theorem_optimizer/autoencoder_family_training_validated_v4.py` | `train_validated_family_projection_autoencoder`, `infer_validated_family_projection_autoencoder` |

The numerical model remains the auxiliary four-tensor structural projection
autoencoder. This path does not train or replace either the historical 8D
linguistic decoder or the 384D source/formula decoder. All emitted projections
must contribute a loss; neither a narrower family request nor an applicability
review may waive the fixed capability floor.

## Inputs and semantic boundaries

Supply a native IntentIR document, exact source text, and an explicit
`context.state.workflow` whose `semantics` is `finite_guarded_state_flow`.
The existing interpreter requires the document hash, evidence references,
finite typed variables and initial values, predicate bindings, action outcome
updates, and retry bounds. It checks preconditions before simultaneous updates
and outgoing edge guards after updates. Variables omitted from an update keep
their values. It enumerates the complete reachable abstract graph or rejects
the projection at its resource bound.

Also supply an immutable `IntentEffectBindings` through
`guarded_effect_bindings`. Its source hash and statement IDs must match the
native document. Every declared effect needs an explicit state expression.
These are caller-supplied interpretations, not verified source semantics or
an executable program inferred from an action verb. A contradictory binding
for the same predicate and ordered arguments cannot silently introduce two
meanings for the same atom.

The new helper replays the native graph and checks declared effects against
every reachable action outcome. A failed outcome is retained, not removed.
An unreachable action cannot establish its effects vacuously. False
preconditions remain deadlocks when no action is enabled. Such models remain
diagnostic targets and fail the training readiness checks. Terminal self-loops
and specification stuttering do not establish eventual completion, fairness,
code execution, permissions, or normative compliance.

The exact source model, original annotations and configuration map are retained.
Only reviewed annotations may be normalized for the existing equality-state
Lean/TLA compiler; the complete model must reproduce from the original inputs.
The report archives the replaced workflow, state and TLA rows under
`superseded_guarded_observations`. The original generic Hoare contract remains
active, and an additional guarded action-contract projection records the
explicit connection between preconditions, updates and effects.

Without the original context and effect declaration, source replay fails.
Embedded report fields and old or serialized execution receipts are not live
authority. Unsupported control/statement roles and other unreviewed projections
continue to block the complete training panel.

For example, after explicitly authoring `document`, `context`, and the source
text, bind the native effect statement `effect` to the finite Boolean variable
`completed` as follows. These names must actually exist in those supplied inputs.

```python
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v6 import (
    IntentEffectBindings, prepare_family_training_targets_v6,
)
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v4 import build_native_family_lake

bindings = IntentEffectBindings.from_dict({
    "schema": "intent-guarded-effect-bindings/v1",
    "source_ir_sha256": source_ir_sha256(document),
    "bindings": [{
        "statement_id": "effect",
        "expression": {"op": "eq", "variable_id": "completed", "value": True},
        "evidence_ref": "source",
    }],
})
inputs = dict(document=document, source_text=source_text, context=context,
              guarded_effect_bindings=bindings)
report = prepare_family_training_targets_v6("intent_ir", **inputs)
execution = build_native_family_lake(
    report, source_inputs=inputs, lake_executable=installed_lake,
    java_executable=installed_java17, tla2tools_jar=installed_tla2tools,
)
```

This prepares and checks the declared inputs; it does not waive other family
requirements. The complete authored example, including all eight supplied
formula families, is in
`optimizers/logic_theorem_optimizer/authored_guarded_intent_panel.py`. The smoke
runner shows the subsequent live policy checks, training and inference calls.

## Run and inspect

Use an explicit `PYTHONPATH` pointing at the canonical checkout or an exact
reviewed export with its own Git root. A HACC-first import is a different
runtime. Native builds use the installed Lake and Java/SANY binaries and do
not download tools, weights or Mathlib.

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/check_native_projection_lake_v4.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/native-default-v4-new

PYTHONPATH="$PWD" python scripts/ops/autoencoder/smoke_guarded_intent_training.py \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --output workspace/test-logs/guarded-intent-new
```

The default matrix gives no implicit guarded interpretations. The separate
authored smoke supplies them explicitly. Its positive cases have stated finite
initial conditions; a separate false-precondition case demonstrates that the
deadlocked branch remains blocked. These fixtures test integration, not
independent corpus holdout fidelity or text-to-formula accuracy.

Only an actual `lake build <Lib>` supplies Lake execution evidence. The checks
validate interpretation definitions and contracts, not source-law truth or
semantic equivalence of natural-language translation. Admission and source-
fidelity flags remain false, and the Constitution remains unformalized.

## Why the previous optimizer epochs were rejected

Read-only replay of the preceding four-domain smoke reproduced its saved
tuning baseline and first training objective. All eight epoch candidates had
worse aggregate tuning loss, so the per-family gate was not the sole reason
for rejection. No run exhausted its deadline.

The diagnostic separates several mechanisms: Legal's denoising gradient
dominated its clean gradient; Security's initial Adam normalization changed a
locally descending raw direction into an uphill tuning direction; Intent/UI
had locally descending first-step directions but worsened at the finite step
size. Gradient clipping was inactive. Constant-feature families were also
perturbed. Small negative cosine roundoff was below the existing tolerance and
was not the blocker.

This is a diagnostic on reused tuning data, not a new holdout or an optimizer
improvement claim. It does not justify weakening the objective or family gate.
A subsequent bounded experiment can compare fixed-noise proposal backtracking
and family-local updates while recording effective learning rate, clean/noisy
loss, direction norm, rejected families, deadline and rollback behavior. A
smaller step cannot guarantee improvement when the direction is already uphill.

## Measured results, 2026-10-01

The frozen candidate passed **71 focused tests**: 35 helper semantics tests,
13 authored-fixture tests, 17 source/gate integration tests, and six default-path
compatibility tests. Real Lake tests accepted the supported model and rejected
deliberately false effect and precondition claims even when the public readiness
guard was bypassed solely for those negative tests. Real SANY parsed the exact
bounded TLA artifact. The tests also cover bounded retries, tampering, stale
bindings, conflicting atom meanings, unreachable actions and nonvacuous floors.

The guarded smoke passed all **69 projection occurrences** over three positive
sources, each with 23 active projections. It executed `lake build IntentIR`
three times and SANY three times, passed both training and tuning gates,
completed two optimizer steps and passed gated inference with every active
projection present in the loss. Total smoke wall time was **28.593 seconds**:
native validation including the negative diagnostic took 22.531 seconds,
numerical preparation 1.937 seconds and optimization 0.033 seconds. Remaining
time includes live-evidence checks and inference.

The negative fixture preserved two initial valuations, four configurations and
one false-precondition deadlock. Its four guarded targets failed readiness and
the strict training gate. A fourth actual Lake build checked the other 19
declarations; it did not validate those four blocked targets. The diagnostic
was excluded from fitting and tuning. No model checker ran.

The selected tuning objective changed from `0.0007063833560527163` to
`0.0007063004818080111` through TDFOL decoder calibration. Neither Adam epoch
was selected. This is an authored structural integration result, not an
independent holdout gain or an improvement to the 8D/384D source decoders.

The default four-modality regression preserved **63/66** supported projection
checks and passed all 32 named-formula cases and three SANY checks. The actual
library builds were `IntentIR`, `SecurityIR`, `UIUXIR` and `LegalIR`. Default
coverage remained 23/23, 16/16, 15/16 and 9/11 respectively; complete default
training panels remain blocked by their existing reviews, floors or opaque
qualifiers. No family, unsupported case or Lake requirement was removed.

Timings came from fresh native workspaces on a shared host while focused tests
ran concurrently. They are not a legal-span or bridge-on autoencoder speed
benchmark. Only new auxiliary checkpoints were written; published runtime
modules and pinned lineage checkpoints were unchanged.

The [evidence manifest](../implementation/reports/evidence/native-intent-guarded-20261001/manifest.json)
binds sources, receipts, failed attempts and the read-only optimizer diagnosis.
[Results](../implementation/reports/evidence/native-intent-guarded-20261001/results.json)
provide the counts and measurements without requiring class-method inspection.
