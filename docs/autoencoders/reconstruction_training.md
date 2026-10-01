# Improving reconstruction without mixing the two lineages

The preserved 8D linguistic autoencoder and current 384D formula autoencoder
train different components. Use the explicit opt-in APIs below. Neither changes
the historical decoder, archived teacher, existing checkpoint source guards,
default trainer, temperature, context limits or qualification requirements.

| Lineage | Learned update in this work | Reconstruction evidence |
| --- | --- | --- |
| 8D linguistic | Existing sparse family-feature logits, with bounded proposal scheduling | Family cross-entropy and real reusable weight changes; the target-aware vector reconstruction cannot establish learned formula fidelity |
| 384D current | Existing residual embedding projection and formula-token GRU, using explicit configuration profiles | Free-running exact rules and seven individual facets, alongside teacher-forced token loss and embedding MSE |

These experiments use authored diagnostic sources and compiler weak labels.
They are not a corpus training campaign or evidence that federal law is
formalized. The Constitution remains unformalized. Only an actual required
`lake build <Lib>` supplies Lean build evidence, and a generated schema passing
that build does not establish agreement with the source law.

## 8D: reach active feature updates under a small budget

The frozen trainer tries two legal-IR-view proposal families before its family
feature proposal. Without metric bridges, those view heads can still use
fallback priors, but a small prefix cap may never reach a proposal that improves
the scored family objective. The new
[active-family helper](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/active_training.py)
directly schedules the existing family update. It retains the frozen strict
objective and regression tolerances. It does not invent a bridge loss or loosen
acceptance.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import (
    LinguisticAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.active_training import (
    train_active_family_features,
)

model = LinguisticAutoencoder(compute_device="cpu")
# Build nonempty, disjoint training/tuning samples with model.build_sample(...).
report = train_active_family_features(
    model, training_samples, validation_samples=tuning_samples,
    epochs=3, learning_rate=0.01, max_line_search_attempts=2, max_seconds=60,
)
model.save_training_checkpoint("workspace/test-logs/new-legacy-checkpoint")
next_learning_rate = report["next_learning_rate"]
```

The helper accepts only the named preserved linguistic profiles on CPU. It is
explicitly bridge-off, disables sample memory and never trains a formula-token
head. Use one private model per writer. The helper does not provide shared-model
thread safety, DuckDB arbitration or multi-machine synchronization.

Each proposal uses a sparse transaction. Rejected, failed, nonfinite or late
proposals roll back. The monotonic deadline includes setup; an in-flight Python
operation may finish after it, but a late candidate cannot commit. The helper
grows the next learning rate only after a first-attempt acceptance and shrinks
it after rejection, within explicit bounds. It does not rewrite an accepted
update or the historical optimizer. Save the report alongside the ordinary
training checkpoint and pass its `next_learning_rate` and the same rate bounds,
growth/shrink factors and attempt cap when resuming the scheduler. Validation
samples select updates and therefore constitute tuning
data, regardless of legacy receipt field names containing “holdout.”

### Preserve the optimizer schedule across restarts

For resumable feature training, use
[FeatureTrainingSession](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/feature_training_session.py)
instead of manually carrying the rate between helper calls. It delegates the
same strict family-feature proposal and saves the learning rate, lifetime
proposal budget, accepted/rejected counts and consecutive rejection count
alongside the ordinary historical model bundle. Restarting cannot replenish
the proposal budget or silently reset the rate.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import (
    ViewReuseHistoricalDaemonAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.feature_training_session import (
    FeatureTrainingSession, load_training_session,
)

model = ViewReuseHistoricalDaemonAutoencoder(compute_device="cpu")
# Build disjoint training_samples and tuning_samples with this model.
session = FeatureTrainingSession(
    model, training_samples, validation_samples=tuning_samples,
    proposal_budget=12, learning_rate=0.01, growth_factor=1.5,
)
first = session.advance(max_proposals=6, max_seconds=60)
saved = session.save("workspace/test-logs/legacy-session-generation-1")
restored = load_training_session(
    saved["path"], expected_sha256=saved["sha256"],
    samples=training_samples, validation_samples=tuning_samples,
)
second = restored.advance(max_proposals=6, max_seconds=60)
```

The controller supports the preserved cached, streamed-cached and historical
daemon linguistic profiles on CPU. Each call has its own monotonic deadline;
the total proposal limit persists across calls and checkpoints. A timed-out
proposal that executed consumes an attempt but does not count as a plateau or
shrink the rate. Unexpected exceptions invalidate the in-memory session; reload
the last completed generation instead of saving an ambiguous state.

Loading requires identical training/tuning inputs, source implementation,
profile, model configuration and saved weights. External model mutation is
rejected. Each save uses a new directory and publishes a final manifest as a
local atomic completion marker; incomplete generations cannot load, and prior
generations are preserved. This is not a guarantee against power loss. The
historical JSON checkpoint cost occurs at explicit saves, not each proposal.
Use one private model per writer; this local controller does not replace the
existing distributed weight coordinator.

## 384D: explicit, source-compatible reconstruction profiles

[formula_training_profiles.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_training_profiles.py)
returns closed, versioned settings for fresh `legal_ir/current_v2` heads:

| Profile | Raw sparse-core initialization | Formula loss / embedding MSE weights |
| --- | --- | --- |
| `baseline_v1` | Scale `0.02`, pairwise skew `0.1` | `1 / 1` |
| `raw_gain10_v1` | Scale `0.2`, pairwise skew `1.0` | `1 / 1` |
| `reconstruction_x10_v1` | Scale `0.02`, pairwise skew `0.1` | `1 / 10` |

All use Adam, learning rate `0.005`, batch six, seed 1729, hidden width 32,
token embedding width 16, projection width eight, and a fixed 1,000-update
comparison budget. The gain intervention multiplies the fresh raw representation
by ten while preserving its direction. It is not a change to the pretrained
embedding producer or formula target. The other intervention increases
embedding reconstruction regularization. Both are development alternatives;
the descriptor alone is no evidence of improvement.

```python
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile

torch.set_num_threads(1)
profile = get_training_profile("raw_gain10_v1")
runtime = open_runtime("legal_ir", "current_v2", **profile["core_options"])
result = runtime.train(
    training_samples, validation_samples=tuning_samples,
    formula_targets=training_targets,
    validation_formula_targets=tuning_targets,
    formula_options=profile["formula_options"],
    **profile["training_budget"],
)
head = runtime.model.save_formula_checkpoint("workspace/test-logs/new-formula-head.json")
restored = open_runtime(
    "legal_ir", "current_v2", **profile["core_options"],
    formula_checkpoint=head["path"], formula_sha256=head["sha256"],
)
```

The gain profile changes the core binding. Always reuse its `core_options` when
loading the saved head; loading it into a default core fails closed. A profile
is not a migration mechanism for an existing trained core or checkpoint. It
requires a fresh branch. The original decoder implementation remains unchanged,
so original heads retain their source compatibility.

## Run the controlled current-model comparison

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/compare_formula_reconstruction_training.py \
  --output-directory workspace/test-logs/formula-reconstruction-new-run
```

Use a fresh directory and a pinned source tree. The script prepares verified
local native 384D embeddings and the shared compiler weak labels once. It fits
only the 24 training rows and observes the six tuning rows from the
[actor-composition panel](actor_composition_evaluation.md). It does not consume
evaluation labels for fitting or selection. The panel has already been exposed
by earlier experiments and is not an independent generalization test.

The runner seals source hashes and settings before fitting. It checks identical
initial decoder weights and vocabulary, actual raw-vector gain, immutable sparse
cores, complete update budgets, exact reload predictions and exact resumed
updates. It saves the scored head before the extra resume-check step. Selection
ranks training exact rules, tuning exact rules, total tuning facet matches,
then negative training token loss. That selects a training candidate, not a
qualified or automatically promoted model.

The selected frozen head generates outputs for all 30 training/tuning sources,
and the runner executes the corresponding Lake schema builds. These structural
checks remain separate from rule fidelity. This head supports the typed deontic
rule projection; it does not establish the full logic-family floor or encode
typed temporal-kind sidecars. Source samples also contain parser-derived
features, so this is not an independent text-only formalizer.

All comparisons record bridge names `[]`, `legal_ir_target_count=0`, provers
disabled, metric disk cache disabled, one metric worker, sample memory disabled
and temperature zero. Thus their timing is not bridge-on legal-IR timing.
Inference timing excludes native embedding preparation and Lake builds.

## Measured reconstruction and feature-training results

The 2026-10-01 runs use committed package
`b1c61836b7811a8dc8aacefef38702794c2786c9` plus the listed new helpers, scripts
and tests in an isolated export. Active unrelated source edits in the shared
checkout are excluded. All result rows and candidate checkpoints are retained
in the [evidence bundle](../implementation/reports/evidence/reconstruction-training-20261001/).

The current decoder received the same 24 training sources and six tuning
sources for each profile. These are greedy generated-rule matches, not
teacher-forced token accuracy:

| Current profile | Training exact | Tuning exact | Tuning actor | Training token CE | Training embedding MSE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 14/24 | 0/6 | 1/6 | 0.070910 | 0.003079 |
| Raw gain 10 | **24/24** | **2/6** | **5/6** | **0.004605** | 0.001318 |
| Reconstruction weight 10 | 15/24 | 0/6 | 1/6 | 0.072921 | **0.000711** |

Increasing raw-input gain improved training reconstruction in this fixed-budget
comparison. It reduced the fraction of conditioning activations with absolute
value above 0.99 from 72.7% to 22.0%. This supports further work on conditioning,
but it does not prove that saturation alone causes all remaining errors.
Increasing reconstruction weight instead produced the lowest embedding MSE
without fixing complete tuning formulas. The four incorrect tuning formulas
remain failures. These are single-seed development results, not a claim about
unseen federal law or convergence to a global minimum.

The final source-bound repeat reproduced all three checkpoint hashes and every
generated training/tuning metric exactly. Trainer-reported wall times were
15.435, 15.511 and 15.353 seconds for baseline, gain and regularization profiles,
respectively. Generation over 30 rows took 0.0475, 0.0457 and 0.0458 seconds per
span. Preparing the 36 shared compiler weak labels took 0.0571 seconds per span,
excluding native embedding production and sample construction. Metric disk
caching was disabled; internal work within a process can still be reused, so
this is not a claim that every span incurred a cold parser invocation. These
timings do not demonstrate a stable throughput improvement. The useful result
is better exact reconstruction at the same update budget.

The separate 8D experiment used three authored training and three tuning
sources, six requested cycles, initial learning rate 0.01 and one line-search
attempt per proposal:

| 8D update path | Accepted cycles | Proposals | Tuning family CE before → after | Training wall seconds |
| --- | ---: | ---: | --- | ---: |
| Original, prefix cap 1 | 0 | 1 | 0.288255 → 0.288255 | 0.751 |
| Original, prefix cap 3 | 6 | 18 | 0.288255 → 0.281454 | 4.487 |
| Active family, fixed rate | 6 | 6 | 0.288255 → 0.281454 | 2.579 |
| Active family, adaptive rate | 6 | 6 | **0.288255 → 0.265801** | 2.359 |

The fixed-rate helper produces exactly the same complete serialized weights as
the successful original path while evaluating fewer proposals. Adaptive rate
growth improves the measured family objective further. All six linguistic
observations remain exactly unchanged; per-sample memory tables stay empty.
Both raw pre-safety and historical safe reconstruction MSE were already zero
and stayed zero. This experiment therefore supplies **no vector-reconstruction
or formula-fidelity improvement claim for 8D**. Its useful improvement is
efficient, accepted numerical feature learning.

Run the retained 8D comparison with:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/compare_legacy_active_training.py \
  --output-directory workspace/test-logs/legacy-active-new-run
```

This is one bounded timing comparison, not a stable throughput benchmark. Its
three-row bridge-off evaluate measured 0.0485 seconds for the original cap-three
path, 0.0525 for fixed active updates and 0.0540 for adaptive updates, or 0.0162,
0.0175 and 0.0180 seconds per span respectively. There is no demonstrated
inference speedup. All bridge/prover/cache/worker/memory flags are the ones
specified above, and no bridge-on evaluate was run.

Checkpoint tests cover exact current-model reload and resumed steps; legacy
tests compare three uninterrupted adaptive cycles with one cycle followed by
save/reload and two more cycles at the persisted rate. The previous 384D head
also reproduced all 30 prior training/tuning outputs exactly. The three typed
canonical gates, empty-vocabulary abstention and five-case pilot remain green;
the pilot measured forward 0.92 and cycle 1.00. The actual canonical minimum-20
`lake build Legal` passes, and the deadline remains non-renderable by that path.
These checks preserve their original scope and do not admit any legal span.

The final release has **243 unique passing tests**, **30 actual generated-schema
Lake builds**, and **one canonical `lake build Legal`**. The archive also retains
an initial preparation attempt that stopped before training when a new source
file appeared, and the subsequent completed comparisons before final guard
hardening. Their observed source files and receipts are preserved. Reported
release results above use the final guarded run; none of these attempts uses a
previously exposed evaluation partition to select a model.

## Continuation and training-wording experiments

The continuation runner compares twelve adaptive feature proposals without a
restart, a manual restart after six proposals that resets the learning rate,
and a saved session that preserves it:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/compare_legacy_training_resume.py \
  --output-directory workspace/test-logs/legacy-resume-new-run
```

The current-model runner compares the same raw-gain profile trained on the
original 24 sentences versus those sentences plus 24 training-only “must”
paraphrases:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/compare_formula_training_augmentation.py \
  --output-directory workspace/test-logs/formula-augmentation-new-run
```

The augmentation is a versioned source fixture, not supplied formula gold.
[formula_training_augmentation.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_training_augmentation.py)
derives it only from the existing training partition and rejects overlap with
other actor/template pairs. The runner separately compiles every variant and
requires its complete canonical rules and typed temporal sidecars to equal
its parent's. A new augmentation requires its own version and screening;
this helper is deliberately not a general-purpose paraphrase generator.

One native local embedding pass covers 54 sources: 24 original training rows,
24 added wording variants and six tuning rows. Compiler weak labels are
prepared once and shared across all six fits. Each seed, 1729, 1730 and 1731,
has identical initial core, head tensors, vocabulary and configuration across
its two arms. Both arms receive 1,000 updates of six rows, or 6,000 row
presentations. The 24-row arm therefore sees 250 epochs and the 48-row arm 125.
Only the formula configuration's seed differs from the named profile between
seed pairs; the script records that override explicitly.

The saved outputs distinguish original training, added wording, the complete
fit set, and tuning. Added wording is unseen wording of trained actor/template
pairs for the baseline, and training data for the augmented arm. Neither is an
independent legal evaluation. No sealed evaluation source is embedded or
compiled, and no evaluation formula is read. All scored checkpoints precede
the extra save/reload/resume check. Every arm is retained; no seed or model is
selected or promoted.

Actual schema Lake builds cover a predeclared four-source panel—report,
prohibition, minimum duration and deadline—for both seed-1729 arms. They do
not cover all sources, seeds or logic families, and do not establish formula
fidelity. Bridge names remain `[]`, target count zero, provers and metric disk
cache off, one metric worker, sample memory off and temperature zero. These
experiments do not supply a bridge-on speed measurement.

### Continuation results, 2026-10-01

The [continuation evidence](../implementation/reports/evidence/training-continuation-20261001/)
uses package base `021e499f743b90122551cd781e6d209ad9ffc751` and the eight
explicitly listed additions in a frozen source export. The shared dirty
checkout and its concurrent parser work are excluded. No archived teacher or
semantic encoder weights were downloaded, changed or included in the archive.

All three 8D paths accepted twelve proposals on three training and three tuning
sentences, starting from family CE 0.288255:

| Continuation path | Final tuning family CE | Training seconds | Save / load seconds |
| --- | ---: | ---: | ---: |
| Uninterrupted | 0.162208 | 4.339 | — |
| Manual restart, rate reset | 0.246293 | 4.863 | 0.021 / 0.218 |
| Persisted session resume | **0.162208** | 6.144 | 0.037 / 0.375 |

The persisted session produces exactly the uninterrupted complete weights and
metrics, and refuses a thirteenth proposal after reload. Correct continuation
preserves learning-rate growth through 0.35; resetting after six proposals
repeats the earlier, smaller rates. Linguistic observations remain identical,
sample-memory tables stay empty, and raw and safe vector MSE remain zero.
This is better continued numerical feature training, not improved linguistic
formula fidelity. Per-proposal integrity checks cost time: the controller is
slower than one uninterrupted helper call in this experiment.

Training wall time divided by three distinct training spans is 1.446, 1.621
and 2.048 seconds respectively across the twelve proposals. Bridge-off
three-row evaluates take 0.0540, 0.0565 and 0.0684 seconds, or 0.0180, 0.0188
and 0.0228 seconds per span. These CPU observations are not bridge-on timings
or a stable throughput benchmark.

For the current model, both arms reconstruct all 24 original training formulas
and all 24 added-wording formulas at every seed. Only the augmented arm trains
on the added wording. Exact tuning-rule reconstruction improves in all three
paired comparisons:

| Seed | Original 24: tuning exact | Augmented 48: tuning exact | Original tuning token CE | Augmented tuning token CE |
| --- | ---: | ---: | ---: | ---: |
| 1729 | 1/6 | **4/6** | 0.165199 | **0.108709** |
| 1730 | 2/6 | **4/6** | 0.186246 | **0.071266** |
| 1731 | 0/6 | **3/6** | 0.168463 | **0.120531** |

These are repeated measurements on the same six development sources, not 18
independent examples. Tuning embedding MSE is mixed: augmentation changes it
from 0.002172 to 0.004898, 0.001121 to 0.001053, and 0.006847 to 0.005557
respectively. Better generated formulas and lower token loss do not imply
every reconstruction objective improved. Remaining tuning errors are retained
as failures. This supports further training-data diversity experiments; it
does not establish unseen-law accuracy or global-minimum convergence.
The baseline already decodes the added wording correctly. This comparison
changes training diversity and minibatch order together; it does not isolate
word choice as the cause of the compositional improvement.

All six runs complete 1,000 updates, taking 15.24–19.69 seconds each. Warm
inference takes 0.0456–0.0462 seconds per row invocation, excluding embeddings,
training, reload probes and Lake. Each arm's inference timer includes repeated
rows in the complete-fit observation: 78 invocations for original24 and 102
for augmented48, not 54 distinct spans. The newly produced embedding batch has
up to 5.96e-8 variation from the previous experiment's shared vectors, and its
seed-1729 baseline yields 1/6 rather than the earlier 2/6. Both arms within
each new pair use identical vectors; the new comparison does not claim exact
reproduction of the old run.

Shared preparation takes 7.86 seconds, including 54 compiler weak targets at
0.0356 seconds per span. Training, inference, checkpoint probes and schema
validation together take another 188.70 seconds. Peak parent-process RSS is
903 MiB; this is not an aggregate of concurrent processes. The metric disk
cache is off and target preparation starts in a fresh process, but internal
reuse means the per-span number is not a cold-parser benchmark.

The release has **279 unique passing tests**, **eight actual generated-schema
Lake builds** on the fixed panel, and **one actual canonical `lake build
Legal`**. All six current heads reload and resume exactly. The three canonical
gates and empty-vocabulary abstention pass. Schema builds are structural checks;
no model is promoted, no law span is admitted by these metrics, and the
Constitution remains unformalized.
