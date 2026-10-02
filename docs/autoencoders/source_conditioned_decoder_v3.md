# Explicit source conditioning for the 384D decoder

`domain-384-typed-autoencoder/v3` is an experimental, separately owned decoder
for testing whether repeated access to a source embedding improves generated
semantic fields. It supports an initial-only control and an every-step
candidate. Both use the same v2 objective, generated-output selection gates,
optimizer policy and numerical deadlines. The completed development comparison
below did not improve exact reconstruction with every-step conditioning. Both
modes learned valid native output syntax, but their selected checkpoints still
lost most source meanings. No new default or production promotion follows.

The design and experiment boundaries are specified in
[source conditioning and semantic reconstruction](source_conditioning_fidelity_ablation.md).
The original 8D linguistic decoder, the trained Legal 384D parent, domain v1,
domain v2 and structured ridge readers remain unchanged. Their checkpoints
cannot be relabelled as v3.

## Public API and domain ownership

The new module is
[`domain_384_autoencoder_v3.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder_v3.py).

| Entry point | Contract |
| --- | --- |
| `train(domain, training_rows, validation_rows, *, parent_projection, config=None)` | Create a new domain checkpoint from a trained Legal 384D parent; an explicit conditioning mode is required in `config` |
| `Runtime(checkpoint)` | Validate a closed v3 checkpoint and its producer, mode, shape and weight bindings |
| `load_checkpoint(path, *, expected_sha256, expected_domain)` | Check the exact file and domain before constructing the runtime |
| `runtime.infer(rows, *, weight_ablation=None)` | Generate native IR tokens greedily from embeddings, without reference targets |
| `evaluate(checkpoint, rows)` | Generate first, then compare with separate reference targets |
| `runtime.describe()` | Report the domain, parent, mode, tensor specification and authority limits |

Domain IDs are `intent_ir`, `security_ir` and `ui_ux_ir`. Each fit produces its
own domain-bound projection, source-conditioning layer, recurrent decoder,
token embedding and readout weights. The common API does not share optimizer
updates or decoder weights between these checkpoints. It also does not replace
the Legal parent's own decoder or any 8D linguistic projection.

Targets use the existing native domain validators: rich Intent AST fragments,
Security program fragments and UI components/documents. The stronger UI
semantic checks inherited from v2 remain in force. Native JSON generation does
not implement every logic-family projection; applicable projection, source
fidelity and native proof checks still run after generation through their
separate versioned owners.

`parent_projection` accepts a trained `modal_latent_formula` Legal checkpoint
object or an exact `{"path", "sha256"}` descriptor. Its dimension must be 384
and its provenance must record completed optimizer steps. A domain v1, v2 or
v3 checkpoint is not a continuation parent for this API. No weights are
downloaded or silently substituted.

## The two conditioning modes

`config.decoder_conditioning` has no implicit default. Callers must choose:

| Mode | Initial state | Input to each GRU step |
| --- | --- | --- |
| `initial_only` | `tanh(condition(normalized_projected_embedding))` | Previous token embedding |
| `every_step` | The identical initial condition | Previous token embedding concatenated with the same source condition |

The recurrent state is an explicit two-lane tensor: lane 0 is the changing GRU
hidden state, and lane 1 carries the immutable source condition. Each request
carries both lanes through training and generation. No model-global source
cache is used, so interleaved requests and reordered batches cannot borrow
another request's source condition.

Transfer first uses the unchanged v1 `base._transfer`: existing projection,
conditioning and recurrent tensors are inherited exactly; matching lexical
rows are copied, and new token rows start from trained parent lexical-row
means. The every-step mode then adds only `hidden_size` input columns to
`decoder.weight_ih_l0`, initializing all added columns to zero. It adds
`3 * hidden_size**2` parameters: 3,072 for the comparison's inherited hidden
size of 32. Hidden-state width, projection width, vocabulary construction and
token ceiling remain the same in both modes.

Consequently the two modes begin with matching shared parameters and the same
initial function, subject to floating-point rounding from differently shaped
matrix operations. The added columns can subsequently learn. Temporary module
initialization does not contribute random replacement weights or alter the
shared initialization. The checkpoint records the inherited initialization
digest and the complete v3 initialization digest separately.

`decoder_spec` records the mode, state layout, tensor names/shapes, total and
baseline parameter counts, and added-parameter initialization. Loading checks
this specification against the configuration and actual tensors, along with
the separate v3 architecture/schema, lineage mapping and producer pins.

`source_conditioning` is a different setting: it controls optional training-only
normalization (`none` or bounded `train_rms`). The comparison uses `none` in
both modes. Normalization applies to the decoder condition; reconstruction
loss still compares the raw projected embedding with the original embedding.

## Prepare, fit and infer

Training and tuning rows have exactly `id`, `source_text`, `embedding` and
`target`. Embeddings contain exactly 384 finite values. Targets must survive
native validation without losing or coercing supplied information. The target
vocabulary is fitted from training only; unsupported tuning tokens and targets
over the token ceiling cause errors rather than truncation or a fallback.

IDs, normalized source texts and embedding hashes must not overlap between
training and tuning. Saved manifests retain both raw and normalized source
hashes, target hashes and embedding hashes. The loader rechecks the recorded
split boundaries. This does not establish semantic-group separation for an
arbitrary caller's data; experiment-level split preparation must do that.

```python
import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    domain_384_autoencoder_v3 as decoder,
)

fitted = decoder.train(
    "intent_ir", training_rows, tuning_rows,
    parent_projection={"path": local_trained_parent, "sha256": parent_sha256},
    config={
        "decoder_conditioning": "every_step",  # Or initial_only control.
        "source_conditioning": "none",
        "epochs": 1000, "max_seconds": 30, "batch_size": 16,
        "learning_rate": 0.003, "reconstruction_weight": 0.1,
        "scalar_value_weight": 8, "max_target_tokens": 64,
        "eval_interval": 10, "patience": 120, "seed": 3517,
        "embedding_nonregression": True,
        "embedding_provenance": verified_embedding_provenance,
    },
)

payload = json.dumps(fitted["checkpoint"], sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
path = Path(new_checkpoint_path)
with path.open("xb") as stream:
    stream.write(payload)

reader = decoder.load_checkpoint(
    path, expected_sha256=hashlib.sha256(payload).hexdigest(),
    expected_domain="intent_ir",
)
inference_inputs = [
    {key: row[key] for key in ("id", "source_text", "embedding")}
    for row in source_rows
]
generated = reader.infer(inference_inputs)
```

Reference targets are forbidden in `infer`. The neural input is the embedding;
`source_text` records provenance and is not parsed into decoder input. The
runtime does not authenticate caller-supplied embedding provenance. A benchmark
must independently check the local encoder assets, captured tokens and
source/vector joins.

Generation is greedy at temperature 0. The ceiling defaults to the parent's
existing token limit and cannot exceed it; the controlled comparison retains
64 tokens. This does not enlarge an encoder context window. Invalid or
unterminated generation retains its tokens and failure disposition; a parser
or reference target never replaces the prediction.

`zero_projection`, `zero_condition` and `zero_decoder` ablations use a model
copy. In both modes, `zero_condition` zeros the condition layer's weights and
bias, removing both the initial and repeated source path. It does not alter
the saved model. Embedding-shuffle diagnostics belong to the caller: keep IDs
and provenance text fixed while permuting vectors, then score the unchanged
row identities separately.

## Inherited loss, selection and optimizer policy

The v3 module directly reuses the pinned v2 loss, generation, normalization,
metrics and selection functions. Its orchestration preserves these rules:

- Scalar values receive token weight 8 by default. Syntax, keys and EOS retain
  positive loss; only padding has weight zero. The objective is weighted token
  cross-entropy plus the configured raw embedding reconstruction MSE.
- Checkpoint selection uses complete, target-free generated tuning outputs.
  No scalar path, exact-target count or native-valid count may regress against
  the best selected candidate. With the comparison's enabled embedding gate,
  MSE must also stay within the initialization bound. Eligible candidates are
  ranked by exact count, scalar accuracy and then the weighted objective.
- One Adam instance runs continuously through the fit, with gradient clipping
  at 5. Candidate objective progress or accepted generated progress resets
  plateau counters. Rejection by a stricter saved-state gate alone is not an
  optimization plateau.
- Evaluations occur at epoch 1, at `eval_interval`, and at the final epoch.
  Plateau learning-rate reduction and patience count completed generated
  evaluations. The default reduction factor is 0.5 after three plateau
  evaluations, bounded below by 0.05 of the initial learning rate.

The numerical deadline covers initial evaluation, optimization, generated
selection and candidate state copying. Partial, incomplete or late evaluations
cannot select a checkpoint. `selected_epoch=0` honestly records that the
returned weights are the transferred initialization even if later optimizer
steps ran but never cleared the gates. Completed optimizer steps alone do not
demonstrate a useful selected model.

This deadline is not a hard wall-clock limit on all preparation, final
selected-model training diagnostics or serialization. Reports separate
optimizer time, validation time, fit time and whole-call time. Callers must
also measure preparation, inference and subprocess work when reporting end-to-end
throughput.

The memory preflight covers the new target model, panels, two state lanes,
added recurrent columns and ablation copies. Parent validation and Python row
processing precede that check. Its conservative tensor reservation explicitly
excludes Python/import overhead, allocator behavior and process RSS. The local
benchmark additionally uses the existing scheduler; its canonical training
lane mapping is a resource reservation, not a claim that training is a Lean
proof operation.

Adam state is not serialized for optimizer resume. This API creates a fresh
fork and does not supply distributed training, shared-writer weight updates,
DuckDB/Quack/DuckLake registration, Hub synchronization or automatic model
promotion. Such integration needs its own versioned checkpoint and coordination
contract; it must not silently reinterpret an old artifact.

## Development comparison and evidence

The bounded driver is
[`benchmark_source_conditioning_development.py`](../../scripts/ops/autoencoder/benchmark_source_conditioning_development.py).
Run it from a frozen source export containing the v3 owner and current native
validation dependencies. It uses only the earlier comparison's exposed
training/tuning files; it must not read or label those earlier test rows as a
fresh holdout.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  /absolute/path/to/frozen-source/scripts/ops/autoencoder/benchmark_source_conditioning_development.py \
  --development-data /absolute/path/to/intent-ui-coverage-20261002/comparison-r1 \
  --parent /absolute/path/to/holdout-throughput-release-20261001/current-holdout-r1/1729-original32-head.json \
  --output /absolute/path/to/new-source-conditioning-development-run
```

This command is the **child benchmark driver**, which obtains inner scheduler
leases but does not itself own the campaign disk ledger. It is not sufficient
on its own to enforce the campaign storage cap. The measured run used the
archived `run_reserved.py` guardian to launch an isolated child under the exact
existing ledger, with a 250 MB storage claim, one outer CPU slot, 4,096 MB memory
and five child-process slots. Its resource receipts retain the outer reservation
and additional conservative inner leases separately.

The evidence archive also retains `validation/run_reserved_next.py`, a later
guardian with stricter process-group cleanup on failure. It requires a fresh
`--attempt` name and refuses the completed `development-r1` directory. That
guardian received focused cleanup tests; it was not the launcher used for these
eight fits. Do not rewrite the completed experiment to imply otherwise.

The output directory must be new. The child driver verifies the pinned local parent,
local GTE assets, stored embedding receipts and exact source/target/vector
joins without downloading. It compares two seeds and both modes for each of
Intent and UI: eight fits, each using 96 training and 24 tuning rows with the
same declared settings. Ordering alternates by seed. It seals checkpoints
before post-fit diagnostics, retains raw generated outputs and all ablations,
and measures warm public-runtime inference separately from embedding, source
auditing and Lake execution.

The driver audits source agreement only after prediction and requests the full
applicable family inventory for predeclared native-check indices. Blocked,
unsupported and failed families remain recorded. Actual `lake build <Lib>`
receipts apply only to the interpretations they checked. Successful numerical
training, generated JSON, source agreement or a partial family build cannot
grant whole-modality qualification.

## Completed development results: 2026-10-02

The release evidence entry point is
[source-conditioning-development-20261002/results.json](../implementation/reports/evidence/source-conditioning-development-20261002/results.json).
The local worker receipt is
`workspace/test-logs/source-conditioning-development-20261002/development-r1/results/summary.json`.
These are exposed training/tuning diagnostics. No fresh test rows were read,
generated or selected in this run.

All eight fits completed **1,000 epochs and 6,000 optimizer steps each**,
stopping on the epoch budget rather than the 30-second numerical deadline.
Each fit saw 96 training rows and the same domain's 24 tuning rows. The two
seeds change minibatch ordering; inherited initial parameters are identical.
Saved checkpoints replayed their complete selected generated metrics exactly.

| Domain | Seed | Mode | Exact/source agreement / 24 | Selected epoch | Selected weighted token CE | Selected embedding MSE |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Intent | 3517 | `initial_only` | 1 | 30 | 0.691467 | 0.001939 |
| Intent | 3517 | `every_step` | 1 | 70 | 0.510756 | 0.002643 |
| Intent | 3518 | `initial_only` | 3 | 200 | 0.287185 | 0.004183 |
| Intent | 3518 | `every_step` | 1 | 40 | 0.682444 | 0.001437 |
| UI | 3517 | `initial_only` | 2 | 940 | 0.386849 | 0.005171 |
| UI | 3517 | `every_step` | 1 | 90 | 0.493929 | 0.003258 |
| UI | 3518 | `initial_only` | 1 | 120 | 0.480414 | 0.004941 |
| UI | 3518 | `every_step` | 1 | 100 | 0.528415 | 0.002009 |

All **192/192 predictions** were typed/native-valid, but only **11/192** exactly
reconstructed their reference and agreed with the source. These are eight
evaluations of reused domain tuning rows, not 192 independent sources.
Initial-only produced 7/96 exact predictions; every-step produced 4/96.
Every-step conditioning improved exact count in none of the four paired
domain/seed comparisons.

The field errors remained substantial. Each count below has denominator 24;
constant fragment-kind fields are excluded so they cannot inflate this view.

| Domain / seed / mode | Correct varying scalar fields, in the stated order |
| --- | --- |
| Intent / 3517 / initial-only | actor 6, action 6, modality 9, object 8 |
| Intent / 3517 / every-step | actor 5, action 8, modality 21, object 8 |
| Intent / 3518 / initial-only | actor 24, action 19, modality 9, object 8 |
| Intent / 3518 / every-step | actor 12, action 8, modality 16, object 8 |
| UI / 3517 / initial-only | component 24, presentation 16, privacy 13, role 8 |
| UI / 3517 / every-step | component 18, presentation 8, privacy 24, role 7 |
| UI / 3518 / initial-only | component 24, presentation 9, privacy 8, role 6 |
| UI / 3518 / every-step | component 24, presentation 11, privacy 8, role 6 |

Selected weighted token loss fell from approximately 3.348 for Intent and
3.320 for UI, and all selected models respected their initialization embedding
MSE bounds. That continuous improvement did not provide adequate semantic
reconstruction. The 808 completed generated evaluations recorded 35 accepted
updates, 419 field-regression rejections, 353 embedding-regression rejections
and one evaluation without selection improvement. Reasons are ordered: a field
failure may also violate the embedding bound, so these categories do not count
every overlapping failure.

For example, later every-step Intent candidates reached 15/24 and 17/24 exact
outputs for seeds 3517 and 3518, but their embedding MSEs were approximately
0.009885 and 0.021868 against an initialization bound of 0.004376. They were
correctly rejected. Those counts describe unsaved development candidates and
must not replace the selected-checkpoint counts in the table.

Zeroing the source condition or decoder produced 0/24 exact and 0/24
native-valid outputs in every fit. Shuffling embeddings produced only 0 or
1/24 exact outputs per fit. These diagnostics establish some dependence on
the learned path; they do not establish faithful source reconstruction.

All **24 predeclared native-check candidates** disagreed with their source.
The source gate therefore prepared **zero native jobs**, executed **zero Lake
builds**, and issued **zero live native qualification observations**. The full
family inventory remained required; it was not reduced to manufacture passing
coverage. Typed/native-valid generation is separate from native proof backend
execution and from source agreement. This run supplies no Lean admit.

### Runtime and resource measurements

| Domain | Seed | Mode | Full training call seconds | Warm inference seconds/span |
| --- | ---: | --- | ---: | ---: |
| Intent | 3517 | `initial_only` | 22.221 | 0.000474640 |
| Intent | 3517 | `every_step` | 27.123 | 0.000488804 |
| Intent | 3518 | `initial_only` | 24.065 | 0.000479799 |
| Intent | 3518 | `every_step` | 24.741 | 0.000498245 |
| UI | 3517 | `initial_only` | 21.062 | 0.000554819 |
| UI | 3517 | `every_step` | 21.151 | 0.000565636 |
| UI | 3518 | `initial_only` | 21.610 | 0.000525952 |
| UI | 3518 | `every_step` | 21.522 | 0.000535145 |

Inference is the median of three warm public-runtime calls over 24 rows,
including native candidate validation, on one CPU worker/thread at temperature
0. It excludes embedding generation, source audits and Lake. No bridge-on
evaluation ran, so these are not legal-IR bridge timings. Training calls include
their preparation and selected-model reporting; the receipts separately retain
optimizer/validation time. Any optimizer examples-per-second field counts
repeated training examples, not distinct corpus spans.

The worker completed in **194.67 seconds**, and its resource guardian completed
in **230.10 seconds**, including census and cleanup overhead. Peak Python-parent
RSS was **951,088 KiB**; that measurement excludes native child RSS. Neither mode
demonstrated an overall fidelity/throughput advantage on this comparison.

Admission required a recorded campaign-storage migration from 90 to **140 GB**
and a census entry bound increase from one to **two million**. The migration
preserved all **65 retained claims** and all root identities; it released no
claims to create headroom and left the **50 GB per-worker limit unchanged**.
The run's own reservation and scheduler lease were subsequently released after
durable output and a fresh accounting check. The `hammer_lean` lane is the
existing mapping for the `canonical_trainer` workload; that lane name and the
resource lease provide no proof evidence. Cooperative admission and polled
usage are not a kernel-enforced memory quota.

The final regression suite passed **266 tests, zero skipped**. The earlier
51-test focused v3 suite is included coverage, not an additional independent
success count. Those tests cover both modes and all three domain IDs, initial
equivalence, sequence/stepwise consistency, interleaving, checkpoint replay,
memory preflight, target rejection, ablation isolation, source pins and deadline
rejection. Synthetic-vector tests establish implementation behavior; the
development results above separately expose its current fidelity limits.

### Next controlled question

A useful next development study is to predeclare a projection-update policy
ablation: `joint` versus `frozen_parent_residual`. The frozen arm would freeze
only `projection_down` and `projection_up`, while continuing to train the source
condition, GRU, token embedding and readout. Both arms must retain the same
embedding bound, scalar-field gates, target ceiling, source audits and applicable
native checks. This is a proposed follow-up, not an implemented or completed
result.

Crossing two projection policies, two conditioning modes, two domains and two
seeds would require 16 equally budgeted fits. Register the shared recipe and
selection rules before fitting, use the exposed development data first, and
keep every rejected evaluation. This can test whether movement in the shared
projection contributes to the observed constraint conflicts. The current
correlation does not prove that it causes them, or that freezing will solve
the field errors. A separately sealed, grouped fresh panel is still required
after any recipe is frozen. No default changes, gate relaxation, fresh-holdout
claim, global-minimum guarantee or production promotion follows from this run.

## Projection-policy follow-up

The separate [v4 projection-freeze study](projection_freeze_development.md)
implements the proposed joint-versus-frozen comparison with the same gates.
Its results and qualification limits are recorded there; this v3 experiment
and its original artifacts remain unchanged.
