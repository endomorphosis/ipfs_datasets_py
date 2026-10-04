# Fit the input boundary while preserving learned decoders

The [dual-donor initialization](gte_decoder_reuse.md) already copies both learned
decoder bodies. This stage supplies a deterministic fit for its new 768-to-384
connection. It fits same-source embedding pairs and leaves inherited weights,
the auxiliary connector and original checkpoints unchanged. The implementation
provides a dependency-free preparation contract, CPU ridge solver and pinned
preparation/fit command. Real multilingual assets remain absent, so the current
corpus has zero paired vectors and no alignment fit has executed.

## Data admission

The command reads externally pinned archive rows, the complete 384D corpus
audit, source tasks, 768D receipts, selected teacher, initial dual-donor bundle
and donor pins. It recomputes bridge pairs rather than trusting a caller-edited
list. The complete student geometry audit preserves old splits and adds new
vector-collision quarantines.

The alignment contract verifies widths, unit-L2 inputs, profile/asset/receipt
identities, pair digests, geometry components and exclusion/coverage counts.
Shared source, document, group, component or duplicate-vector identities cannot
cross fitting and validation. Test/canary rows and quarantined components remain
excluded; no rows move between splits.

At least two distinct training pairs are required. A grid of candidates also
requires validation pairs. A single predeclared lambda may fit training-only
with validation metrics explicitly unavailable. Limits reject oversized input
rather than truncate: at most 4096 train pairs, 4096 validation pairs and 16
increasing distinct regularization candidates.

Partial receipt coverage can supply an experimental fit if these conditions
hold. Reports retain coverage status and missing counts. Vector alignment uses
no IR labels, so teacher-prediction and unlabeled rows may supply vector pairs
without becoming reference supervision. Producer authenticity and semantic
qualification remain separate requirements.

## Deterministic ridge initialization

Let x be a source's new multilingual 768D vector and y its archived raw 384D
vector. Fit only training pairs:

~~~text
minimize_W,b sum_train ||W x + b - y||² + lambda ||W||_F²
lambda > 0; intercept b is unregularized
~~~

Compute both means from training rows only. With centered X and Y:

~~~text
W.T = solve(X.T X + lambda I, X.T Y)
b = mean_y - W mean_x
~~~

For fewer than 768 train rows, solve the smaller dual system:

~~~text
W.T = X.T solve(X X.T + lambda I, Y)
~~~

The solver uses one CPU thread and float64 arithmetic, then exports float32
weights. Predictive metrics execute that exported boundary and accumulate errors
in float64. A finite solve-residual check rejects numerical failure. Report the
centered rank upper bound; no exact rank is claimed. The proposed Legal corpus
has 360 train tasks, so its first affine fit remains underdetermined even with
complete receipts and needs regularization.

Lambda uses the **summed** residual objective. A mean-row lambda would require
conversion by training-row count. The initial grid is 0.001, 0.01 and 0.1;
these are candidates, not measured choices. Every candidate fits training alone.
Validation selects the smallest mean squared-L2 error, with ties choosing the
smaller lambda. Never refit with validation. One fixed lambda with no validation
performs no selection. Report coordinate MSE, per-vector squared-L2 and cosine
error separately; zero predictions have unavailable cosine.

Fit raw archived 384D coordinates. The copied decoder applies its saved input
transform exactly once afterward. Do not normalize, clip or truncate adapter
outputs. Adapted coordinates retain a distinct identity and are not genuine
GTE-small producer outputs.

## Preparation and fitting

The new
[configuration](../../configs/autoencoders/gte_affine_alignment_preparation_v1.json)
has mode prepare and binds the immutable initialization and archived teacher
source tree. Preparation imports no Torch and fits nothing, even if pairs later
become available. From the repository root, use a fresh output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_alignment.py \
  --config configs/autoencoders/gte_affine_alignment_preparation_v1.json \
  --expected-config-sha256 f4cc89345ba4bc30b2a174edd3036b6c2471f7ebbd1f14e2df44a10bc3307653 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-affine-alignment-preparation-20261001/reproduction-01
~~~

The command writes pairs, a split-specific plan, teacher and initialization
bindings, summary and completion manifest. Missing pairs produce an explicit
unavailable outcome with zero candidate fits and no replacement vectors.

Once real receipts arrive, create a new configuration binding their bytes and
set its explicit mode to fit. Declare its grid, partitions and resource budget,
then invoke the command with its new SHA256. Fitting runs in a separate bounded
offline CPU process. It saves a separately versioned fitted bridge and fit report
with exact bridge reload, per-candidate metrics, row digests and initialization
binding. It executes no encoder, optimizer updates or KD loss.

The [aligned decoder handoff](gte_aligned_decoder.md) now admits the completed
fit manifest, bridge, plan, report and immutable initialization into a private
student. It replaces only the input adapter, preserves all 26 inherited tensors
and the auxiliary connector, and authenticates exact saved reload. The fit
report binds the current aligned identity; the original initialization's identity
and bytes remain historical. A preparation-only parent emits zero aligned
checkpoints. A ridge fit does not clear semantic qualification or every alignment
requirement.

The 32-to-8 auxiliary connector remains initialized. Its fit requires declared
original 8D latents or supported grammar references; later scoped 8D KD must
still reach the shared student. Continued 384D improvement can supply another
pinned donor generation. All three lanes retain separate model processes,
optimizers, caches and checkpoint writers.

## Implementation and evidence

The new files are
[alignment contract](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_alignment_contract.py),
[numerical fitter](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_affine_alignment.py),
and [CLI](../../scripts/ops/autoencoder/prepare_gte_alignment.py).
Numerical tests fit explicitly synthetic normalized pairs. Those matrices are
diagnostic fixtures, not multilingual encoder results or production bridges.

This stage's artifact directory is
~~~text
/home/barberb/lift_coding/artifacts/gte-affine-alignment-preparation-20261001/
~~~
Previous planning documents are preserved under inputs-01/previous-documents.
All 143 files in the prior decoder-reuse verification matched at this stage's
start. The new ledger distinguishes intentional document updates from unchanged
donor initialization, source implementations and earlier model-smoke evidence.

The current preparation receipt is run-02. It completed in 3.83 seconds, reports
480 missing eligible multilingual receipts, and selects zero training and
validation pairs. All 720 prior quarantined rows remain excluded. No fit,
encoder execution, optimizer update or KD occurred. The source task handoff
retains 360 Legal train tasks and 120 Legal validation tasks for later receipts.

| Receipt | SHA256 |
| --- | --- |
| run-02/manifest.json | d51b1e626b89834060a086cb3dd8becf787860aa4b1edf7733ec71d6b0571c6b |
| run-02/plan.json file bytes | 23fc0f3c6396119bea2daed03cd44565ef54576aead876979d11acfaa7cbff26 |
| Plan's internal content digest | 0edee0d132800d1bcbf8cef579e36625717c0a8043bef0748c1f086380434fd3 |

The initial run-01 is retained. A metadata correction now keeps a multi-candidate
grid's declared validation selection policy when missing validation blocks
fitting; the previous module bytes are preserved under inputs-01. Both runs
report zero fits. The corrected plan never describes three candidates as a
fixed single-candidate policy.

Validation covers 153 new alignment checks: 31 contract checks, 69 numerical
checks and 53 CLI checks. The main run passed 957 checks, including the retained
805; after the metadata correction the focused 153-check run passed. Across the
retained and current suites, 958 distinct checks are covered. Logs are saved
beside the preparation runs. Ready-fit tests use real ridge solving and bridge
reload on synthetic inputs; they establish implementation behavior rather than
multilingual model or student fidelity.
