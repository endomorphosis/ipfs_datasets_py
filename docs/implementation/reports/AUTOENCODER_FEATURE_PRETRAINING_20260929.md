# Parallel feature pretraining before compiler distillation

Feature pretraining is now an explicit training purpose. The deterministic
compiler/decompiler repairs are deferred; they do not block learning private
feature weights. Formalization qualification and publication keep their
existing semantic, logic-family, and source-locked Lake requirements.

## Training objective and evidence

Use `--training-purpose feature_pretraining` on the existing incremental
runner. It selects `projection_reconstruction_objective=raw_decoder`, which
uses the learned reconstruction before the input-dependent safety projection
for residual updates, hard-example ranking, and candidate acceptance. Simply
changing the reported metric was insufficient: the old projected residual
could be zero while the learned reconstruction was poor.

The optimizer keeps its cross-entropy and legal-IR objective terms, explicit
regression tolerances, bounded line search, adaptive learning rate/momentum,
deadline handling, and sparse update rollback/replay. The default
`formalization` purpose retains the existing projected objective and unchanged
qualification policy. Default job serialization also stays unchanged.

Each feature job requires disjoint tuning rows, complete finite raw decoder
observations, supplied semantic embeddings, all five bridges, a verified shared
target artifact, disabled sample memory and provers, and metric disk cache off.
The Python sparse batch backend remains selected. Raw mode rejects unproven
precomputed evaluations and the unsupported CUDA-resident path.

Compiler-derived IR targets remain supervision with known semantic gaps. A
target, optimizer acceptance, reconstruction score, checkpoint, or DuckDB row
does not admit a law. Feature receipts explicitly report `qualified=false`,
`formalized=false`, `admitted=false`, and semantic qualification deferred. They
do not submit source repair tasks or use the qualified Hub publication route.

## Inputs and resumption

`--feature-input-manifest` binds input and validation JSONL files to an existing
local embedding-production receipt. Verification checks source selectors,
text/model identity, exact float32 vector bits, split membership, and retained
oversize abstentions. The CLI also binds its already parsed records to those
verified file hashes, rejecting replacement between the two reads. No weights
are downloaded, no text is truncated, and no context window is expanded.

The current local receipt supports pinned GTE-small 384-dimensional vectors.
The adapter also accepts `autoencoder-feature-inputs/v1` manifests with explicit
ordered training/validation input IDs; it does not expand the underlying
embedding producer's supported models. Canary JSONL and canary source files
are neither opened nor evaluated. The existing diagnostic corpus retains its
unverified global provenance flags despite verified local vector production.

Feature training uses a fresh, purpose-bound state directory and a separate
model variant. Existing DuckDB owner lanes persist progress; Quack coordinates
mutations while workers train private state and emit replay-verified sparse
updates. Hardware capacity determines physical wave width independently of
the persistent lane topology. Rejected updates retain their parent. Exact
duplicate intake verifies durable lane heads without retraining consumed rows.

Use the frozen canonical-source launcher from
[the source integration runbook](AUTOENCODER_SOURCE_INTEGRATION_20260929.md)
for both target preparation and training. This keeps one immutable source
generation throughout the run while other contributors prepare changes.
Use absolute manifest/runtime paths. Apply the target handoff's
`runner_environment` before training and resume; the target timeout is part of
its provenance and must match even when targets have already been prepared.

```bash
python scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --training-purpose feature_pretraining \
  --feature-input-manifest /ABSOLUTE/embedding-split.json \
  --input-jsonl /ABSOLUTE/training.jsonl \
  --validation-jsonl /ABSOLUTE/tuning.jsonl \
  --checkpoint /ABSOLUTE/LOCAL/compatible-parent.state.json \
  --shared-targets /ABSOLUTE/shared-targets/targets.bundle \
  --target-snapshot-id sha256:EXACT_PREPARED_TARGET_SNAPSHOT \
  --target-shard-max-bytes 268435456 \
  --state-directory /ABSOLUTE/CHARGED/NEW/feature-training \
  --workers 4 --parallel-workers 2 --reuse-training-workers \
  --max-batches 6 --epochs 3 --max-seconds 180 \
  --line-search-attempts 2 \
  --projection-optimizer-mode productive_adaptive \
  --projection-momentum 0.25 \
  --projection-candidate-update-order decoded_embedding_structural \
  --memory-mb 24576 --storage-bytes 650000000 --cycle-timeout 360
```

Paths, budgets, parent dimension, and target bounds must describe the actual
prepared input. This example is a small smoke configuration. Reusing its six
training rows for a long run would not establish broad feature quality.

## Validation scope

The raw decoder remains conditioned on the original embedding through the
existing initial projection. This change enables residual feature learning;
it does not establish an independent semantic decoder, successful compiler
distillation, or a global optimum. Later distillation needs separate held-out
fidelity and unchanged formalization evidence. The Constitution is not
formalized.

The isolated scoped Git candidate passed **668 tests**, including the existing
qualified runner, worker, CLI, optimizer, and resource suites. The validator
supplied pinned copies of the two required JevOps dependencies outside its
temporary checkout; it did not edit JevOps. See the
[validation receipt](evidence/autoencoder-feature-pretraining-20260929/isolated-source-validation.json).

The native parallel smoke passed with six training rows, two repeated tuning
rows, two physical workers, and four stable logical lanes. Two lanes were
occupied with three batches each. All six batches accepted all three epochs:
**18 accepted epochs**, with replay-verified sparse checkpoints and native
Quack owner transport. Workers kept private state; one owner wrote DuckDB.

| Private lane | Accepted epochs | Raw tuning cosine | Raw reconstruction loss |
| --- | ---: | ---: | ---: |
| 1 | 9 | 0.196116 → 0.843544 | 0.00252708 → 0.00187983 |
| 3 | 9 | 0.196116 → 0.826895 | 0.00252708 → 0.00187753 |

Training calls overlapped in all three dispatches, with conservative overlap
lower bounds of 5.420, 4.374, and 4.016 seconds. These bounds compare summed
worker training-call time with the encompassing dispatch wall time. They are
not inner-loop CPU utilization measurements. Training including frozen
launcher setup took 159.508 seconds; identical-input resume took 51.876 seconds
and dispatched **zero jobs**, preserving both lane heads. The independent
canary was neither read nor evaluated.

An earlier completed diagnostic hashed all six batches to one of two logical
lanes. It accepted 18 epochs and resumed correctly, but demonstrated no
parallel training. The four-lane topology above was selected from the same
immutable batch hashes before the second run. Both attempts and their exact
scope are retained; no loss-based selection was used to choose the topology.

Cold target generation for all eight spans took 115.104 seconds, or
**14.388 seconds/span**. The full preparation handoff including input planning
took 147.662 seconds, or 18.458 seconds/span. The parallel run reused those
exact targets from the same frozen source generation; it did not regenerate
them. Bridge-on autoencoder evaluation measurements were:

| Samples / legal-IR targets per evaluation | Evaluations | Mean wall seconds | Median wall seconds |
| --- | ---: | ---: | ---: |
| 1 / 1 (training cache preparation) | 6 | 1.501 | 1.767 |
| 2 / 2 (tuning and candidate selection) | 42 | 1.488 | 1.448 |

All measurements used `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, and `external_prover_router`; provers false, metric disk cache 0,
sample memory false, and one requested IR worker. Evaluations supplied verified
shared targets and therefore generated no new targets. Their timing excludes
the separately reported cold generation cost. The Python sparse batch backend
and empty `CUDA_VISIBLE_DEVICES` were retained.

See the [compact results](evidence/autoencoder-feature-pretraining-20260929/summary.json)
and [parallel evidence](evidence/autoencoder-feature-pretraining-20260929/parallel-feature-smoke.json).
Native execution used canonical-path frozen manifest
`99101d3813dbe67ed836c15a019153a3f12b6595b5e6e30c91d1298baf59cbd1`.
That capsule records the canonical workspace generation, including its
pre-existing changes. Scoped Git publication excludes the unrelated automatic
bridge-worker default hunk; both native runs explicitly requested one IR
worker. These are separately identified source observations, not a claim that
the entire live workspace equals the published Git tree.

The smoke fixed a tuple/list JSON resume comparison and an omitted target
timeout handoff. It also added complete bridge-supervision checks before raw
training, including the streaming target reduction path. Failed launches and
the interrupted source-validation attempt remain recorded. No Lake build,
source-repair dispatch, model promotion, or Hub upload occurred in feature mode.

The campaign storage cap is 87 GB following the requested headroom increase.
The 50 GB per-worker bound and all retained historical claims remain intact.
Failed attempts are retained; only dead claims with explicit durable closeout
are released. No claim is expired automatically.

## Progression toward distillation

1. Expand verified local embeddings over a versioned federal-law training
   split, retaining source selectors, language/model identity and abstentions.
   Keep independent validation sources separate from optimizer tuning.
2. Prepare each immutable generation of bridge targets once. Run bounded
   parallel feature jobs with raw reconstruction, IR loss and per-epoch
   productivity evidence; continue each private lane from verified sparse
   updates. Compare learning per wall-clock time as well as epoch duration.
3. Select feature checkpoints using a broader held-out evaluation, including
   ablations of the input-conditioned reconstruction and downstream tasks.
   The current six-row diagnostic does not justify an eight-hour quality run.
4. When compiler/decompiler repairs resume, distill from selected feature
   checkpoints into their learned heads, then apply source-semantic,
   logic-family and actual Lake qualification before formalized publication.

Private feature lanes are separate model versions. This change does not
average concurrent lanes into one globally synchronized model or publish
unqualified feature candidates as formalized span evidence.
