# Training the 384D source decoder against generated-output fidelity

The `domain-384-typed-autoencoder/v2` runtime trains source-conditioned native
IR fragments with a scalar-aware token objective and selects checkpoints using
their actual generated outputs. It retains the parent architecture and token
ceiling. Syntax validity, exact reference reconstruction, source fidelity and
proof qualification remain separate measurements.

This is a separate lineage from the complete structural-feature heads described
in [complete features and UI fidelity](complete_features_and_ui_fidelity.md).
Those heads reconstruct compiler-produced feature vectors. This runtime takes a
384-dimensional source embedding and generates native JSON tokens. The older
8D linguistic decoder and `domain_384_autoencoder` v1 are unchanged.

## Entry points and lineage

The module is
`ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_autoencoder_v2`.

| Entry point | Contract |
| --- | --- |
| `train(domain, training_rows, validation_rows, *, parent_projection, config=None)` | Fork a trained Legal 384D parent into an Intent, Security or UI checkpoint |
| `Runtime(checkpoint)` | Validate and load a v2 checkpoint |
| `load_checkpoint(path, *, expected_sha256, expected_domain)` | Check file identity, domain and producer pins before returning a runtime |
| `runtime.infer(rows, *, weight_ablation=None)` | Generate greedily from source embeddings; target fields are forbidden |
| `evaluate(checkpoint, rows)` | Generate without targets, then compare with separate reference targets |
| `runtime.describe()` | Report lineage, dimensions, source conditioning and authority limits |

Supported domain IDs are `intent_ir`, `security_ir` and `ui_ux_ir`. The parent is
a trained 384D `modal_latent_formula` Legal checkpoint, supplied either as a
checkpoint object or an exact `{"path", "sha256"}` descriptor. It must have
completed optimizer steps. This API does not accept a v1/v2 domain checkpoint
as a resume parent or an 8D checkpoint as a substitute.

Projection, conditioning and recurrent tensors are inherited from the parent.
Matching vocabulary rows are copied; new target-token rows start from the
trained parent's lexical-row means. No random replacement tensors or enlarged
hidden layer are introduced. The artifact retains the parent's identity,
transfer description, complete training/tuning manifests, source pins,
normalizer and weight digests.

The v2 checkpoint format does not silently migrate a v1 artifact. Training is a
fresh fork with a new Adam optimizer. Its momentum persists during that fit but
is not serialized for continuation. There is no automatic DuckDB/Quack/DuckLake
registration, shared-writer coordination, Hub upload, distributed resume or
checkpoint promotion in this API. Those require their own versioned integration.

An independent inference adapter can batch **existing, unchanged v1 weights**:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    domain_384_batched_inference,
)

reader = domain_384_batched_inference.load_checkpoint(
    existing_v1_checkpoint_path, expected_sha256=existing_v1_sha256,
    expected_domain="ui_ux_ir", batch_size=8,
)
generated = reader.infer(inference_inputs)  # id, source_text, embedding only
```

This reader first validates the v1 artifact with the unchanged v1 loader. It
retains every tensor, vocabulary entry and token limit, and applies no source
normalization or training. It adds the same strict UI semantic validation used
by v2, retaining raw JSON and separate envelope/semantic dispositions when the
stronger boundary rejects a candidate. It does not migrate or rewrite the
checkpoint. Batched arithmetic can differ in rounding; output equivalence must
be measured before calling it a drop-in readout for a particular checkpoint.

The separate regression command is:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  scripts/ops/autoencoder/benchmark_domain384_batched_inference.py \
  --comparison /absolute/path/to/completed-source384-comparison \
  --output /absolute/path/to/fresh-batched-readout-comparison
```

It loads each of the four saved v1 checkpoints once per runtime, reuses all 36
already exposed rows per checkpoint, warms both runtimes once, then records 20
paired repeats with alternating order. The serial timed call includes the same
stronger native validator. Tokens, EOS, raw/native candidates and validation
dispositions must agree exactly; reconstructed embeddings must differ by at
most `1e-6` per coordinate. Any mismatch fails the comparison with retained
outputs. Median, interquartile range, seconds per span and throughput refer to
CPU inference including native validation, excluding model loading, warmup and
comparison. This is a readout regression, with no training or new holdout claim.

## Prepare rows and train a bounded candidate

Training and tuning rows have exactly four fields:

```python
{
    "id": "unique-source-id",
    "source_text": "The librarian must catalog the packet.",
    "embedding": verified_source_embedding,  # Exactly 384 finite values.
    "target": {
        "kind": "intent_rich_ast",
        "document": {
            "kind": "atom", "actor": "librarian", "action": "catalog",
            "modality": "required", "object": "packet",
        },
    },
}
```

Each split is bounded and nonempty. Duplicate IDs and cross-split overlaps in
IDs, normalized source texts or embedding hashes are rejected. Targets must
survive their native validator without dropped, reordered or coerced supplied
fields. The target vocabulary is fitted only on training rows. Missing tuning
tokens and oversized targets raise errors instead of receiving an unknown-token
or truncated-target fallback.

For UI, v2 also invokes the existing semantic component owner through
`ui_source_contract_384.validate_training_target`. This enforces the closed
privacy/presentation vocabularies and semantic component restrictions; complete
document component graphs receive their graph checks. The older `UIComponent`
envelope alone accepts strings such as `privacy_sensitivity="interactive"`,
which this stronger boundary correctly rejects. Input targets and generated
predictions must both pass it. The owner and its component definitions are
included in v2 producer pins.

The neural input is the embedding, not `source_text`; text records source
provenance. The general runtime does not authenticate caller-supplied embeddings
or their claimed model. The benchmark below performs that separate verification
using the existing local GTE-small assets and actual captured forward tokens.

```python
import hashlib
import json
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    domain_384_autoencoder_v2 as decoder,
)

fitted = decoder.train(
    "intent_ir", training_rows, tuning_rows,
    parent_projection={"path": existing_parent_path, "sha256": parent_sha256},
    config={
        "epochs": 1000, "max_seconds": 30, "batch_size": 8,
        "max_target_tokens": 64, "seed": 1729,
        "scalar_value_weight": 8, "source_conditioning": "none",
        "eval_interval": 10, "patience": 12,
        "embedding_nonregression": True,
        "embedding_provenance": verified_embedding_provenance,
    },
)

# Use a new file; the parent remains immutable.
path = Path(fresh_checkpoint_path)
payload = json.dumps(fitted["checkpoint"], sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
with path.open("xb") as stream:
    stream.write(payload)
runtime = decoder.load_checkpoint(
    path, expected_sha256=hashlib.sha256(payload).hexdigest(),
    expected_domain="intent_ir",
)
inputs = [{key: row[key] for key in ("id", "source_text", "embedding")}
          for row in inference_rows]
generated = runtime.infer(inputs)
```

Inference does not accept expected targets, teacher forcing or sample-memory
lookups. It performs batched, greedy generation at temperature zero. Individual
rows stop at EOS or an invalid special token; failures retain generated tokens,
termination status and errors. A valid candidate remains unqualified.
`zero_projection`, `zero_condition` and `zero_decoder` ablations operate on a
model copy, leaving the saved weights unchanged.

## Loss, selection and learning-rate behavior

Canonical JSON scalar **values** receive weight 8 by default, including strings,
identifiers, numbers, booleans and nulls at every path. This includes constant
values such as a fragment kind; it is not a hand-picked list of favorable
semantic slots. Keys, punctuation and EOS retain weight 1. Padding has weight
zero, and BOS is an input token rather than a prediction target.

The differentiable objective is the mean weighted token cross-entropy plus
`reconstruction_weight × MSE(projected_embedding, original_embedding)`. Every
non-padding token remains in the objective. Ordinary unweighted token
cross-entropy is reported separately, so a different weighting does not create
an apparent improvement merely by changing the metric.

Checkpoint selection adds generated-output checks after inference. JSON parsing
rejects duplicate keys and malformed output. Typed comparisons retain missing
and extra fields, scalar types and ordered array positions. With a domain
validator requested, invalid native outputs receive no scalar correctness
credit. Reference values never become fallback generated values.

A candidate cannot replace the current best if any expected scalar path loses
correct predictions, its exact-document count falls, or its native-valid count
falls. By default its embedding MSE must also remain at or below the initial
transferred model's tuning MSE, allowing only the numerical tolerance `1e-12`.
Eligible candidates are ranked by exact count, scalar-field accuracy, then lower
weighted objective. The embedding veto is against initialization, not an
additional guarantee that every accepted step improves on the previous model's
embedding error. The initial checkpoint can remain selected when later steps
fail these gates.

Optimization progress and checkpoint acceptance have different roles. A
rejected candidate can still reduce the continuous trajectory's weighted loss.
That progress resets the learning-rate plateau and patience counters, as does
an accepted generated-fidelity improvement. Rejection alone therefore does not
reduce the learning rate. After three completed evaluations without either kind
of progress, the default schedule halves the rate, stopping at 5% of its initial
value. Adam's moments persist across rate changes.

| Setting | API default | Meaning |
| --- | ---: | --- |
| `epochs` | 80 | Maximum training epochs |
| `max_seconds` | 180 | Numerical deadline described below |
| `learning_rate` | 0.003 | Initial Adam rate |
| `batch_size` | 8 | Training and generated-evaluation batch size |
| `seed` | 1729 | Training permutation seed |
| `reconstruction_weight` | 0.1 | Raw projected-embedding MSE weight |
| `scalar_value_weight` | 8 | All JSON scalar values; keys/syntax stay at 1 |
| `eval_interval` | 10 | Generated evaluation also occurs at epoch 1 and the final epoch |
| `patience` | 12 | Completed evaluations without selection or objective progress |
| `plateau_patience`, `plateau_factor` | 3, 0.5 | Learning-rate plateau schedule |
| `min_learning_rate_ratio` | 0.05 | Minimum rate relative to the initial rate |
| `embedding_nonregression` | `True` | Veto against initial tuning embedding MSE |
| `source_conditioning` | `"none"` | No embedding normalization change by default |
| `memory_budget_bytes` | 512 MiB | Conservative numerical tensor reservation |
| `max_target_tokens` | Parent's limit | May be reduced; cannot exceed the parent |

Training reports expose both token losses, generated exact/native counts,
per-path correctness, selected epoch, optimizer steps, examples and tokens seen,
selection reasons, candidate-objective progress, learning rates, patience,
timings and memory estimates. Tuning is used to select checkpoints and schedule
rates; it is not an independent holdout.

## Conditioning, resource bounds and deadlines

`source_conditioning="train_rms"` is an optional experiment. It fits a vector
mean `μ` and a single L2 RMS using **raw training embeddings only**:

```text
r = sqrt(mean_i(sum_j((embedding[i,j] - μ[j])**2)))
scale = max(r, 1 / 64)
decoder_initial_hidden = tanh(condition((projected_embedding - μ) / scale))
```

The normalization affects decoder conditioning only. Reconstruction still
compares the raw projected embedding with the original embedding. The saved
mean, scale, training-embedding digest and maximum gain are validated at load
time; tuning and inference do not refit them. This is one scalar scale, not
per-coordinate standardization. `"none"` stores zero mean and unit scale.

The runtime uses CPU float32 and temporarily sets PyTorch to one thread under
the existing runtime lock. Inference is batched, whereas v1 generates one row at
a time. This does not launch parallel trainers automatically. The memory
estimate includes input panels and conservative parameter, optimizer, gradient
and minibatch-logit workspaces. It excludes Python objects, imports, allocator
overhead, semantic-encoder residency and process RSS. An oversized estimate
raises an error. Checkpoints retain the 48 MiB artifact bound.

`max_seconds` begins before initial numerical/generated evaluation. It covers
optimization, generated evaluation, comparison and candidate state copying.
Generated evaluation checks its deadline between batches, decoding steps and
fidelity rows. An incomplete evaluation cannot select a checkpoint. A late
state copy cannot be accepted either. Initial evaluation can exhaust the budget
before a usable training step, in which case the call fails.

Parent loading, target/vocabulary preparation, model allocation, final reporting
and checkpoint serialization/validation also take time. They are not a hard
process limit under `max_seconds`. Measure the outer training call separately
from `optimizer_seconds`, `validation_seconds`, `fit_seconds` and intermediate
whole-call telemetry. These bounds do not permit target truncation, vocabulary
omission or skipped projection qualification.

## Development evidence behind these choices

The earlier four-training/two-tuning Intent and UI fragment examples are already
exposed development data. They confounded actor with action and component ID
with role. Native-valid generated output still had wrong actions, modalities,
roles or privacy values despite lower teacher-forced loss.

A bounded diagnostic kept the inherited hidden size 32, projection width 8 and
64-token ceiling. With the same diagnostic loop, scalar weighting improved UI
training exactness from 1/4 to 4/4 and exposed tuning exactness from 0/2 to 1/2.
Those are development observations, not a fresh holdout claim or a validation
of every v2 change. The old UI references used envelope-valid `sensitive` and
`informational` values that the stronger semantic owner rejects. Their retained
results are numerical/envelope diagnostics, not successful semantic-native
validation. The new comparison uses owner-valid values and scores both versions
through the same stronger owner. Other variants damaged embedding reconstruction, supporting
an explicit reconstruction veto and retaining unmodified conditioning by
default. The diagnostic's centering used parent-projected vectors and
per-coordinate RMS; it is not an evaluation of v2's raw-input L2 RMS option.

The small training sets could reach exact 4/4 reconstruction without a wider
hidden layer. Increasing capacity is therefore not the first demonstrated fix.
The diagnostic also found weak source sensitivity at some generated positions.
A source-conditioning ablation and exact per-field reporting remain necessary;
well-formed JSON alone cannot establish source use or semantic correctness.

## Reproduce the sealed comparison

Use a frozen source tree with the existing trained local parent and the pinned
local `thenlper/gte-small` snapshot. The benchmark verifies all nine encoder
assets, loads with `local_files_only=True`, checks actual untruncated forward
tokens, and records the resulting 384D vectors. It downloads no weights and
does not raise the encoder's existing token ceiling. The generated-target
ceiling remains 64.

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/ops/autoencoder/benchmark_source384_fidelity.py \
  --output /absolute/path/to/fresh-source384-comparison \
  --parent /absolute/path/to/existing-trained-legal384-parent.json \
  --parent-sha256 969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62
```

The panel has 24 training, six tuning and six test compositions per domain.
Intent crosses three actors, four actions and three modalities; UI crosses
three component IDs, four roles and three privacy values, with presentation
values also varied. Every actor/action or component/role pair appears with two
semantic settings in training. The third setting is assigned to tuning or
test by a fixed rule. All target tokens are covered by training vocabulary.
The UI privacy values are `none`, `high` and `restricted`; presentation values
are `interactive` and `static`, following the existing semantic owner.

Two fixed seeds compare unchanged v1 with v2 `source_conditioning="none"` and
scalar weight 8. Both use up to 1,000 epochs and a 30-second numerical budget.
V1 patience is 120 epochs; v2 patience is 12 completed generated evaluations,
with interval 10 and the plateau defaults above. This is a comparison of the
complete training paths, not an isolated attribution to one setting.

All eight fits, their settings and checkpoint hashes are frozen before the
twelve test source/target rows or their embeddings are constructed. The test
is then evaluated once with actual conditioning and with zero conditioning.
Once observed, it must not be reused as a fresh holdout. Native fragment
validity, exact equality, per-slot errors, ordinary cross-entropy, embedding
reconstruction and public inference time are recorded for each seed.
The common benchmark applies the stronger native validator to both v1 and v2
predictions. It reports envelope validity separately, preserves raw parsed
candidates and errors, and gives no exact or scalar credit to a prediction that
fails the stronger native contract. This comparison does not change v1's loader
or training behavior.

The benchmark retains `plan.json`, source/asset/data hashes, training reports,
all checkpoints, `freeze.json`, `test-exposure.json`, generated outputs and
`summary.json`. Its 2 GiB headroom preflight is an observation, not an exclusive
memory reservation. Peak RSS includes the cached semantic encoder and the whole
mixed benchmark process. Timings use alternating strategy order without a
separate warm-up phase; report them as descriptive public-API measurements.

## Results and remaining qualification work

The completed `comparison-r1` did **not** improve source reconstruction with
v2. Across the two seeds, exact Intent test reconstruction fell from 3/12 to
1/12; UI remained 0/12 for both versions. Correct reported critical slots fell
from 35/48 to 29/48 for Intent and from 28/48 to 21/48 for UI. V2 remains an
experimental training path; no candidate was promoted.

Each domain/seed comparison below scores six test rows and 24 reported critical
slots. Intent slots are actor, action, modality and object; UI slots
are component ID, role, privacy sensitivity and presentation classification.
These diagnostic slots do not replace the complete typed-target comparison.

| Domain | Seed | Exact v1 → v2, /6 | Critical slots v1 → v2, /24 | Ordinary token CE v1 → v2 | Embedding MSE v1 → v2 |
| --- | ---: | --- | --- | --- | --- |
| Intent | 1729 | 2 → 1 | 17 → 15 | 0.063771 → 0.371839 | 0.005888 → 0.001663 |
| Intent | 1730 | 1 → 0 | 18 → 14 | 0.072681 → 0.277726 | 0.005903 → 0.001577 |
| UI/UX | 1729 | 0 → 0 | 15 → 11 | 0.114355 → 0.309406 | 0.004195 → 0.002077 |
| UI/UX | 1730 | 0 → 0 | 13 → 10 | 0.123276 → 0.708342 | 0.007599 → 0.002754 |

All 48 conditioned predictions passed the applicable local native boundary.
The low exact counts show why that is insufficient. V2 preserved embeddings
better but reconstructed the source targets worse. Ordinary cross-entropy also
increased; this conclusion does not depend on comparing differently weighted
losses. Zeroing the conditioning weights produced zero native-valid predictions
out of 48 for both versions combined. That ablation shows dependence on the
conditioning pathway for valid generation, not correct discrimination of the
source's semantic choices.

The CPU comparison took 63.48 seconds overall, including cached GTE preparation
and eight fits. Peak process RSS was approximately 0.94 GiB, including the
semantic encoder. Public inference for six test rows took 15.04–15.20 ms for
Intent v1 and 5.23–5.25 ms for Intent v2; UI took 13.63–13.69 ms for v1 and
5.56–5.64 ms for v2. These are descriptive single-call timings with different
selected weights and no separate warm-up. They neither isolate batching nor
justify promoting the poorer reconstructions. The shared stronger scoring ran
outside these timers, so the public APIs also performed different validation
work. The same-weight readout
comparison below provides the appropriate separate performance test.

### Why v2 kept early checkpoints

The development traces show that v2 continued training through epochs 330–490.
It stopped on generated-validation patience, with fit times of 4.04–5.79 seconds,
not because its 30-second deadline was exhausted. Selected epochs were 70 and
80 for Intent, and 70 and 50 for UI. V1 selected epochs 546, 474, 398 and 639,
respectively.

Later v2 candidates reduced the continuous weighted objective but regressed
protected fields. Intent modality counts regressed in 36 and 41 evaluated
candidates. UI privacy counts regressed in 26 and 42; role counts regressed in
26 and 21. For example, Intent seed 1729 eventually reached 6/6 tuning actor and
action matches while modality fell from the selected 3/6 to 1/6. UI seed 1729
reached 6/6 component-ID and presentation matches while privacy fell from 4/6 to
1/6 and role from 3/6 to 0/6.

Across the four traces, 110 rejected evaluations violated both the generated
fidelity gates and the initial embedding-MSE bound; 36 violated only the
generated gates and 14 only the embedding bound. The primary rejection reason
alone hides the combined cases because generated regression is checked first.
Candidate loss improvements correctly kept learning active after the last
accepted checkpoint; rejection alone did not trigger rate reduction.

The embedding term's small continuous contribution and its separate hard veto
constrain different aspects of training. The evidence supports improving the
objective and source conditioning together with balanced development data. It
does not justify removing the protected-field checks, choosing new settings
from this exposed test, or claiming convergence to a useful semantic optimum.

### Native follow-up: successful partial UI builds, no qualification

`native-checks-r1` used the first stored test row for each domain/version at seed
1729, without selecting successful examples. It separately checked the first
training row where the primary result was inexact, blocked or lacked a
successful Lake execution. The four training diagnostics did not replace the
four primary results. All eight sampled predictions were reference-inexact.

All four Intent attempts stopped before Lake: the existing rich-AST contract
requires exact complete agreement with the source parser. No Intent Lean build
ran for those candidates. Both primary UI candidates and both separate UI
training candidates completed actual `lake build UIUXIR` commands using the
installed Lean 4.30.0 toolchain.

Those four successful builds have a narrow scope. Each UI candidate prepared
one frame-logic projection covering component identity, role and relationship
facts. The other 39 requested registry families remained explicitly missing;
the native status was `partial`. Privacy policy, presentation behavior,
accessibility compliance, temporal interaction, authorization and program
bindings remained unprojected. A successful build of that partial generated
artifact does not prove its relationship to the source or qualify the complete
modality. The follow-up took 16.29 seconds, changed no weights and ran no new
solver diagnostics. All admission, formalization and qualification flags remain
false.

### Same-v1-weight batching results

`inference-comparison-r1` passed on all four unchanged v1 checkpoints and all
144 unique model–row pairs. Tokens, EOS, raw/native candidates, validation
dispositions and errors agreed exactly, including repeated-call stability.
The maximum embedding-coordinate difference was `1.4901161193847656e-7`, below
the `1e-6` bound. Source, inputs, checkpoint bytes and local encoder assets were
unchanged. No model training or selection occurred; these were already exposed
regression inputs, not a new holdout.

Both readers were loaded once per checkpoint and warmed once. The measurements
use 20 alternating paired repeats, CPU float32 with one PyTorch thread, and
inference batch size eight. Each call processes 36 rows. Serial calls include
the same stricter native validator inside the timed region.

| Domain | Seed | Median ms/span, serial → batched | Spans/second, serial → batched | Median speed ratio | 36-row call IQR ms, serial → batched |
| --- | ---: | --- | --- | ---: | --- |
| Intent | 1729 | 2.224 → 0.531 | 449.7 → 1882.3 | 4.19× | 0.397 → 0.290 |
| Intent | 1730 | 2.240 → 0.544 | 446.4 → 1839.2 | 4.12× | 0.508 → 0.283 |
| UI/UX | 1729 | 2.109 → 0.612 | 474.1 → 1633.9 | 3.45× | 0.439 → 0.098 |
| UI/UX | 1730 | 2.110 → 0.612 | 473.9 → 1635.1 | 3.45× | 0.634 → 0.379 |

The complete readout comparison took 12.34 seconds. Peak process RSS was
522,920 KiB, approximately 0.50 GiB; no semantic encoder was loaded. The timing
includes public inference and native validation, with construction, warmup,
output persistence and comparison outside the per-call timer. It supports using
the batched reader for these existing weights without changing their outputs.
Their source-reconstruction errors remain unchanged. This is neither a training
speed result nor a legal-IR bridge evaluation, and it grants no qualification.

[Results and evidence](../implementation/reports/evidence/source384-fidelity-20261001/results.json)
retain the full per-seed outcomes, development rejection analysis and native
commands. The adjacent `manifest.json` indexes `evidence.tar.gz`, including
producer pins, input/asset hashes, generated outputs and native artifacts.

This benchmark covers authored Intent rich-AST and UI component fragments.
Security is supported by the API but is not measured by this panel. It does not
test a new Legal source decoder or the historical 8D teacher.

UI component semantic validation is still local to the supplied component or
component graph. A component fragment does not establish complete document
reference closure, event/backend bindings, policy correctness, observed
behavior or successful modality projections. Accepting a closed-vocabulary
privacy value is not proof of its appropriateness for the source or application.
Security program-expression fragments also
need their enclosing program to establish reference and type correctness.

Qualification still requires reconstructing the complete applicable modality
IR, checking every emitted logic-family projection through its actual owner,
preserving unsupported cases and counterexamples, and running the real
`lake build <Lib>` for the relevant generated Lean library. Compiler output,
native parsing, a loss decrease, an exact authored fragment, a solver diagnostic
or a database row is not a Lean admit. No Mathlib import, model download,
Constitution formalization, automatic proof status or promotion is introduced
by this training path.
