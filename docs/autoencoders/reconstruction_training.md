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
