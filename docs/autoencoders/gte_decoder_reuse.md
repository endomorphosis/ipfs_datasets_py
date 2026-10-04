# Reuse learned 8D and 384D decoders before 768D training

The first 768D student inherits learned decoder weights from both sizes. Start
with those weights, align its new connections, then distill supported behavior.
Keep the 8D and 384D paths running as independent lineages. The
[migration plan](gte_multilingual_migration_plan.md) now uses this order as the
default; a fresh random decoder is an optional comparison.

Weight transfer and distillation have different prerequisites. Exact compatible
weight copying needs authenticated tensors, vocabularies and input conventions.
It does not require a semantic qualification score. Training on donor predictions
does require independently qualified scope and screened supervision. Low training
loss alone does not establish accurate free-running IR reconstruction. The
[source-only comparison](gte_decoder_source_evaluation.md) now evaluates both
raw original donors from their existing inputs and compares available saved
768D generations on the same sources. The original 60-row validation panel is
exposed regression evidence; the two authored 8D training examples are
diagnostics. Independent fidelity and per-head KD gates remain separate.

## Which learned work transfers

| Donor | Copied into the first student | Limits of the current evidence |
| --- | --- | --- |
| Selected 384D source reconstruction decoder | All 13 tensors: residual projector, conditioning layer, token embeddings, GRU and output layer; 25,224 parameters; exact typed-JSON codec with 32 vocabulary entries and identity normalization | Exposed tuning panel has 0/60 exact targets; no admitted KD scope |
| Experimental 8D latent formula decoder | All 13 tensors: projector, conditioner, token embeddings, GRU and output layer; 1,918 parameters; exact grammar codec with 18 vocabulary entries | Two synthetic training examples, parser-derived inputs, fresh 8D core; no admitted KD scope |
| Full historical 8D checkpoint | Preserve its learned feature/family/view tables for later scoped auxiliary targets and relational supervision | Contains no formula GRU or vocabulary; target-aware reconstruction is not neural decoder fidelity |
| Small linguistic 8D bundle | Preserve its classifiers and separately identified compiler weak labels | Formula-head-present is false; compiler formulas are not learned head generations |

The learned 8D head comes from
~~~text
workspace/test-logs/modal-joint-e2e-20261001-final/legacy_v1/formula-head.json
SHA256 ffca84492b81ab94fa291ae6ddbe52cfc84318f3516a22f901d468de255b6cbe
weights e96a6e3ff5771b9227aa98919aee2745d42cd3361e0f85d5d2771ed88e9d1995
codec 25d32d252ce8ef0fab2b6315068898fa3205246bc5f8abfad1ffbce8a1bfd6e1
~~~

Its core binding is
~~~text
5d750c7d9142f590770a9123c5a68fde0ceb1e6ba5cb1dd0574faeb452f4d36b
~~~
It is not the complete historical 8D checkpoint. Verify the five recorded
implementation files under the existing archived source tree before admission.
The new helper ports the learned architecture into private Torch state; it does
not claim that the current original runtime replays that sidecar.

The selected 384D donor is
~~~text
/home/barberb/lift_coding/artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json
SHA256 6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61
weights 17ddd2026a72eda808e5223cc32c5c6fd0b523fc2ec771f620c9b3179793a05a
codec cba3e5384e2bee12e709ccc8e9ee430e51cf09a8fc2e8abdd57143fdaa38dba2
~~~

During this stage the shared checkout's UI decoder changed. The existing
~~~text
/home/barberb/lift_coding/artifacts/legal-ir-inference-speed-review/audit/baseline_tree
~~~
matches all 14 of the selected 384D donor's implementation pins. Use that tree
for donor admission. Do not relabel the old checkpoint with new source hashes or
revert concurrent changes. The previous bridge verification remains immutable;
the new preservation receipt records its one pre-existing source mismatch.

## First student architecture

~~~text
frozen multilingual encoder -> 768D source vector
    -> new 768->384 affine input adapter
    -> copied 384D normalization / projector / conditioner
    -> shared 32D condition
         -> copied 384D GRU and typed-JSON output head
         -> new 32->8 connector
              -> copied 8D projector / conditioner / GRU / grammar output head
~~~

The auxiliary branch receives the shared primary condition. Its future loss
therefore reaches the primary input adapter, rather than training an unrelated
head in isolation. Do not detach the shared condition or run student training
through inference-mode wrappers. Freezing copied parameters preserves gradients
with respect to their inputs.

Both heads start from their learned donor values. Only the 295,296-parameter
768-to-384 boundary and the 264-parameter auxiliary connector need alignment.
The existing pinned bridge can initialize the boundary, but that bridge is
untrained. There is no justified coordinate conversion by zero-padding, slicing
or averaging old weights. Adapted 384D coordinates retain their own identity;
they are never labeled as genuine GTE-small vectors.

The initial branch has 27,142 copied parameters and 295,560 new interface
parameters. Both copied bodies start frozen. Start a fresh private optimizer for
the interfaces; do not import either donor's Adam moments or training cursor.
Later selective unfreezing creates a separately recorded training generation.

The primary decoder keeps its 512-output-token budget; the grammar head keeps
64. The multilingual producer accepts up to 8,192 input tokens including special
tokens. Longer encoder context does not change an IR output codec or output
budget. Decoder coverage and output length expansion require separate work.

## October preparation and November fitting sequence

1. **Snapshot and initialize.** Pin checkpoint files, all tensors, exact codecs,
   source implementations and transforms. Copy both complete decoder bodies into
   private state. Verify float32 equality, no aliasing, nonzero input gradients
   through frozen bodies, and exact self-contained reload. Save initialization
   evidence separately from any future fitted checkpoint. Refresh the 384D donor
   snapshot if October improvements produce a better tuning-selected candidate.
   The [knowledge replay and export](gte_decoder_knowledge_transfer.md) now
   checks both copied heads against independent donors using their original
   cached training inputs and exact reference prefixes before interface fitting.
   For the selected 384D codec, use the compatible V2 cohort first; all 480 Legal
   V3 development references require explicit vocabulary migration. The 8D
   raw latents are reconstructed from its original two cached synthetic inputs
   and checked against the original training manifest.
   The [native input join and reference objective](gte_decoder_native_inputs.md)
   then bind matching 768D receipts and carry independently normalized reference
   losses through the new interfaces while both inherited bodies remain frozen.
   The [bounded reference interface trainer](gte_decoder_interface_training.md)
   can fit those four new tensors from the original inherited initialization
   and publish a distinct generation with exact post-training output replay.
   Current preparation has no ready native inputs and performs zero updates.
2. **Produce actual paired inputs.** Use original source text for the pinned
   multilingual CLS/L2 producer. Start with sources fitting both tokenizers.
   Preserve group/split identity, reject overlength inputs and quarantine new
   vector collisions. Fit only on training rows; use validation only for
   selection. Keep the encoder frozen. Real multilingual assets and receipts are
   still missing, so no alignment fit has run.
3. **Align new interfaces.** With both copied bodies frozen, initialize or fit
   the affine adapter from same-source 768D/384D training pairs. A train-only
   regularized least-squares fit can replace its seeded values before gradient
   training. The [alignment preparation and fitter](gte_affine_alignment.md)
   now implements that step with training-only centering, separate validation
   selection and immutable initialization. The [aligned decoder loader](gte_aligned_decoder.md)
   then replaces only the two fitted adapter tensors in a private student,
   preserving both learned heads and the original initialization. No real pair
   fit has run. Do not
   compute coordinate MSE across unrelated raw dimensions.
   Train the auxiliary connector from matched declared 8D latents when that
   original pipeline is reproducible, or from supported reference grammar loss.
   Preserve the 8D donor's projector/input convention; a missing raw latent is
   not recovered by taking the first eight embedding coordinates.
   The current reference pilot starts from the original initialization; using
   the completed aligned handoff as its start is now implemented by the separate
   [aligned-start interface trainer](gte_aligned_interface_training.md). It binds
   the exact fitted starting state and preserves the original runner.
4. **Distill within each head.** Keep reference targets authoritative. For the
   primary head use reference CE plus scoped 384D KL. For the grammar head use
   separately normalized reference CE and scoped 8D KL. Authenticate donor
   qualification reports, checkpoint identities and exact reference-prefix
   exports before admitting any KD token. Initially both donors have zero
   admitted KD supervision; inherited weights are still useful initialization.
5. **Consolidate learned behavior.** Monitor held-out free-running reconstruction,
   varying semantic fields, unsupported vocabulary and critical logical errors.
   Add per-donor ablations. Once interface alignment stabilizes, selectively
   unfreeze copied primary tensors at a smaller learning rate, record any
   auxiliary unfreezing, and reduce KD weight if it preserves donor mistakes.
   Keep unchanged frozen donor snapshots for comparison.
6. **Promote and expand.** Compose the learned conditioner into a direct
   768D-input architecture while preserving its function. Check logits and
   gradients with fixed-profile numerical tolerances, and check generation
   stability before fitting. Floating-point reassociation can change bits even
   when the algebra is equivalent. Expand
   hidden capacity only with a declared function-preserving construction or
   teacher-assisted fit. Then extend input context through 512, 1024, 2048, 4096
   and 8192 tokens. Use references or a separately qualified long-context teacher
   where the old 512-token source teacher cannot see the whole input.

The production ordering is dual-donor initialization, interface alignment,
reference/scoped KD, selective tuning, direct conditioner promotion, then context
expansion. None of these stages retires an existing lane. Each lane keeps its
own representation, model process, writer, optimizer, caches and checkpoint
namespace. The new student does not become a published registry default merely
because its preparation probe succeeds.

## Separate aligned distillation losses

The new
[loss helper](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_distillation.py)
implements temperature-scaled KL per head, following the
[knowledge distillation objective](https://arxiv.org/abs/1503.02531). For each
head, match teacher/student codec and canonical reference-prefix digests; record
raw versus grammar-masked distributions, donor checkpoint, qualified scope and
qualification-report pin. It detaches teacher logits and excludes masked tokens.
Qualification pins are declarations until authenticated by the experiment
admission layer; the loss helper does not grant qualification.

~~~text
L = CE_reference_primary + alpha * T² * KL_384_per_valid_token
  + beta * CE_reference_grammar + gamma * T² * KL_8_per_valid_token
  + delta * train_only_interface_alignment
~~~

Choose and record weights on validation; declare T=2 as a first candidate and
compare T=1. Report eligible/excluded token counts and each head's loss and
gradient contribution. Different head vocabularies and sequence lengths remain
separate. Combine scalar losses after each head is normalized; do not combine
their logit arrays. All-masked heads contribute differentiable zero. Teacher
reference prefixes are training-only inputs; free-running inference starts from
BOS without targets.

The current 8D vocabulary supports a narrow obligation/agency/submit grammar
with notices and reports. Exclude other atoms and unsupported projections from
that donor's supervision. Extending a codec later requires an explicit
training-only token mapping, new-row initialization and a new checkpoint identity.
Compiler-derived weak labels, generated teacher labels and authored references
keep separate origins and masks.

## Preserve behavior during native conditioner promotion

For the trained affine adapter a(x)=W x+b, donor normalization mean mu and scale
s, let B=W/s and q=(b-mu)/s. The copied donor projector and conditioner are
~~~text
z = B x + q
y = z + U tanh(D z + d) + u
h = tanh(C y + c)
~~~
The equivalent direct 768D conditioner is
~~~text
h = tanh((C B) x + (C q + C u + c)
         + (C U) tanh((D B) x + D q + d))
~~~
Preserve the residual tanh term; collapsing the whole conditioner into one
linear layer changes its function. Copy the existing embedding, GRU and output
tensors unchanged. The shared condition remains compatible with the 8D
auxiliary connector. For the current widths this direct conditioner uses 31,016
parameters plus 6,368 recurrent/token/output parameters; the 8D branch remains
separate. These are future algebraic parameters, not an implemented/promoted
checkpoint or evidence of increased decoder capacity.

## Preparation APIs and evidence

The new implementation files are
[primary warm start](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_warm_start.py),
[8D donor port](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_legacy8_decoder_donor.py),
[dual-donor initializer](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_reuse.py),
and
[bounded preparation CLI](../../scripts/ops/autoencoder/prepare_gte_decoder_reuse.py).
Inspection imports no Torch, model assets or transformer code. Numerical loading
creates private CPU float32 state and requires a bounded worker with one Torch
thread. Authenticate complete saved JSON bytes and supply the six external donor
file/weight/codec pins before strict reload.

From the repository root, reproduce preparation into a new output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_decoder_reuse.py \
  --teacher384 /home/barberb/lift_coding/artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json \
  --teacher384-sha256 6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61 \
  --legacy8 workspace/test-logs/modal-joint-e2e-20261001-final/legacy_v1/formula-head.json \
  --legacy8-sha256 ffca84492b81ab94fa291ae6ddbe52cfc84318f3516a22f901d468de255b6cbe \
  --repository-root /home/barberb/lift_coding/artifacts/legal-ir-inference-speed-review/audit/baseline_tree \
  --legacy-implementation-root workspace/test-logs/legacy-teacher-release-20261001/source \
  --bridge /home/barberb/lift_coding/artifacts/gte-affine-bridge-preparation-20261001/probe-01/untrained-bridge.json \
  --bridge-sha256 98dc9da97252483b752c3134ca0d5445fcd4c923294fc954548715f2689d1077 \
  --threads 1 --memory-limit-mib 16384 --cpu-time-limit-seconds 120 \
  --output /home/barberb/lift_coding/artifacts/gte-decoder-reuse-20261001/reproduction-01
~~~

The preparation command emits an initialization bundle, external donor pins,
tensor counts, a synthetic dual-branch gradient/reload probe, resource accounting
and an implementation/input-bound manifest. The probe uses a synthetic unit
768D vector and BOS-only prefixes. It runs no encoder, optimizer or fitting and
does not establish distillation quality. The artifact location for this stage is
~~~text
/home/barberb/lift_coding/artifacts/gte-decoder-reuse-20261001/
~~~
Prior planning documents are preserved under inputs-01/previous-documents.
The verification ledger records old receipt preservation, existing source drift
and the current files separately. Actual alignment, qualified KD and generated
student fidelity remain outstanding.

The October 1 preparation run at run-01 completed in 4.61 seconds. It verified
all 26 copied tensors against the actual donor payloads, frozen inherited heads,
finite nonzero auxiliary gradients on all four new interface tensors, unchanged
weights and gradient buffers, and exact saved reload with independent storage.
The synthetic input was explicitly not a multilingual encoder result.

| Receipt | SHA256 |
| --- | --- |
| run-01/manifest.json | 2b8017707f5619262b6cdf1d86f73035322fa6f3a9e5a521c2a42c029bf55cde |
| run-01/student-initialization.json | 7443c8a60cb1f95e9a35017edcd394c0f47fd457c3733e0863d37bfc09a09a12 |

Validation passed 805 focused checks: 494 retained preparation checks and 311
new decoder-reuse/loss/CLI checks. The main run passed 785 checks and the separate
CLI run passed 20. Logs are saved beside run-01. The earlier 23-file parallel
model smoke receipt remains unchanged. No encoder execution, optimizer updates,
fitting or completed distillation occurred in this stage.
