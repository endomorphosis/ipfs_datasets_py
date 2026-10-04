# Connect inherited decoder targets to native 768D inputs

This stage prepares the first reference-supervised objective for the inherited
768D student. It reuses the original 384D embeddings, reconstructed 8D latents,
saved decoder tensors and detached teacher distributions. Native inputs come
from exact matching cached multilingual receipts; missing sources stay explicit
embedding tasks. Both inherited decoder bodies remain frozen while their new
input connections receive reference-loss gradients.

## Original sources and complete split audit

The source cohort contains 242 original sources: 180 V2 Legal training rows,
60 V2 validation rows and the two authored synthetic 8D examples. The full
source, group and split audit precedes selection of the existing 16 primary and
two auxiliary replay rows. Validation remains outside the training objective.
The original 8D sample vectors retain their distinct provenance and do not
enter the 384D embedding geometry audit; their source text and references do.

The [batch contract](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_native_batch.py)
uses the existing corpus auditor, multilingual task contract and
[cache reuse helper](gte_embedding_reuse.md). It retains quarantines and
deduplication outcomes. Source-only tasks contain the original text and audit
metadata, with no reference content or cached donor vectors passed to the
encoder. Donor inputs and reference-prefix targets remain in the separate
training plan.

Each ready row binds the original batch row, exact native task and receipt,
donor codec, source hash, prefix hash, shifted reference labels and detached
teacher logits. Receipt admission requires the pinned multilingual profile,
selected asset manifest, 768 finite unit-normalized coordinates and a token
receipt within 8192 input tokens. Old vectors remain donor inputs and supervision
targets; dimensions and producer identities are never relabeled.

Selected-batch readiness and complete-cache coverage are separate. All 18
selected rows must have admitted native receipts for the objective or gradient
probe. A ready selected batch may still lack other cohort receipts, including
validation; its full cache status and missing tasks remain visible.

## Reference objective through the new connections

The [objective](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_native_objective.py)
accepts a private student and an inspected ready plan. For each primary row,
the 768D vector passes through the new input adapter and copied 384D conditioner
to the typed-JSON head. For each auxiliary row, the same shared condition passes
through the new auxiliary connector to the copied 8D grammar head. Auxiliary
loss therefore reaches the primary input adapter as well as its connector.

Each head computes reference cross-entropy over its eligible next-token
positions and divides by that head's eligible token count. Weighted scalar
losses are then combined; the two vocabularies and token positions stay
independent. The saved teacher distributions keep their source and prefix
bindings for later scoped KD, which remains disabled in this stage.

The optional gradient probe creates a private student, evaluates the objective
and calls backward. It checks finite, nonzero gradients on all four new
interface tensors, absent gradients on all 26 inherited tensors, and exact
unchanged model state. It creates no optimizer and performs zero updates.
Synthetic receipt fixtures exercise this implementation in tests; they never
enter a production task or cache.

## Preparation command

The [command](../../scripts/ops/autoencoder/prepare_gte_decoder_native.py)
authenticates the completed decoder replay's entire input, implementation and
output closure before joining native inputs. The original validation archive
has its own external file hash. Current helper implementations are pinned and
rechecked around preparation and publication.

From the repository root, use a fresh output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_decoder_native.py \
  --config configs/autoencoders/gte_decoder_native_preparation_v1.json \
  --expected-config-sha256 0bc3b0913591db96643c7409abe6403727037418a21f26421582db072b2d2721 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-decoder-native-preparation-20261002/reproduction-01
~~~

The [configuration](../../configs/autoencoders/gte_decoder_native_preparation_v1.json)
uses `mode: prepare`, which invokes no numerical model even if the cache is
ready. A separate pinned configuration may use `mode: probe`; the probe runs
only for a ready selected batch, on one CPU thread with bounded memory and CPU
time. Incomplete inputs produce explicit unavailable or partial results with
zero numerical execution. Neither mode invokes an encoder or downloads assets.

Outputs include the native training plan, full source-only task manifest,
missing tasks, reused receipts, inspection receipt and summary. Probe mode
adds resource and gradient receipts when eligible. Saved plan bytes are
authenticated and inspected again before the completion manifest is written.
Input and implementation namespaces are protected from output writes.

## Next fitting step

When the pinned assets are available, the existing producer can consume the
saved missing-task list directly. This command is recorded for that later
step; it has not been run in this stage:

~~~bash
python scripts/ops/autoencoder/prepare_gte_multilingual.py embed \
  --tasks-file /home/barberb/lift_coding/artifacts/gte-decoder-native-preparation-20261002/run-01/missing-tasks.json \
  --expected-tasks-sha256 b55c6c5669cc6a9c64346c640cb252f2a0a1d9929df6d319a66b534621374ff8 \
  --asset-manifest configs/autoencoders/gte_multilingual_local_assets_v1.json \
  --expected-asset-manifest-sha256 8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166 \
  --model-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/model \
  --code-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/code \
  --batch-size 1 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-decoder-native-preparation-20261002/native-embed-01
~~~

Use a new pinned configuration to bind the returned receipts. A partial cache
combines its unchanged admitted receipts with the newly produced missing ones
by exact task ID; unrelated cohort IDs and duplicate entries are rejected.
Keep the completed preparation and original cache generations immutable.

1. Reuse matching native receipts or encode only the missing original sources
   with the pinned multilingual producer when its assets are available.
2. Fit the primary input boundary on original training pairs and select it on
   validation, using the [affine fitter](gte_affine_alignment.md) and
   [aligned student handoff](gte_aligned_decoder.md). The auxiliary connector
   remains separately supervised.
3. Attach the ready native batch to a separately identified aligned student and
   use this reference objective to train the interfaces with a fresh optimizer.
   Record a new checkpoint generation and compare free-running reconstruction
   against the original donors and the inherited initialization.
4. After donor scope validation, admit screened per-head masks and teacher
   qualification evidence, then add the existing temperature-scaled KD loss.
   Vocabulary migration and longer context remain later, explicit generations.

The [bounded interface trainer](gte_decoder_interface_training.md) now
implements a reference pilot from the original inherited initialization. It
updates only the four new connections, preserves all 26 learned tensors and
publishes a distinct checkpoint verified against its actual post-training
outputs. Its current production preparation remains unavailable with zero
updates. Step 3's [aligned-start training](gte_aligned_interface_training.md) now
has a separate runner that admits the completed affine-aligned generation.
Actual inputs still lack native receipts and an executed fit, so neither path
performs production updates.

The [decoder knowledge guide](gte_decoder_knowledge_transfer.md) records the
exact copied-head replay. Reference gradients through native inputs, optimizer
updates and distillation have distinct receipts and acceptance criteria.

## Actual preparation result

The [completed run](../../../../artifacts/gte-decoder-native-preparation-20261002/run-01/manifest.json)
reproduced the independent
[source and asset audit](../../../../artifacts/gte-decoder-native-preparation-20261002/source-asset-audit.json)
exactly. Its 242 rows form 22 source components, with zero quarantines and zero
deduplications. All 18 selected replay rows remain eligible, and validation
stays outside the objective.

| Cohort | Source tasks | Cached native receipts | Selected replay rows ready |
| --- | ---: | ---: | ---: |
| Original V2 primary training | 180 | 0 | 0 of 16 |
| Original V2 primary validation | 60 | 0 | Outside training |
| Original synthetic 8D training | 2 | 0 | 0 of 2 |

The selected batch and full cache both report `unavailable`. The declared
multilingual model/code directories are absent, and both existing declared
native receipt files are empty. No native model or gradient probe executed.
The preparation saved the
[native input plan](../../../../artifacts/gte-decoder-native-preparation-20261002/run-01/native-batch.json),
[full source-only task manifest](../../../../artifacts/gte-decoder-native-preparation-20261002/run-01/tasks.json)
and [242 missing tasks](../../../../artifacts/gte-decoder-native-preparation-20261002/run-01/missing-tasks.json).
Exit code 1 means this preparation completed with missing selected inputs;
invalid input or execution errors use code 2. The
[execution receipt](../../../../artifacts/gte-decoder-native-preparation-20261002/execution.json)
records the actual command and output hashes. Donor initialization and cached
old embeddings remain unchanged; optimizer and encoder execution counts are
zero.

The focused suite passed **322 checks in 348.17 seconds**: 170 new checks
(70 native join, 47 reference objective and 53 command checks), plus 152 retained
distillation and dual-decoder checks. Ready native numerical cases use explicit
synthetic receipts only in tests. These checks cover per-head CE arithmetic,
auxiliary gradient flow, unchanged inherited tensors, independent state,
source-root protection and authenticated saved plan/probe inspection. The
[test receipt](../../../../artifacts/gte-decoder-native-preparation-20261002/tests-01/result.json)
binds the command and logs, and the
[verification receipt](../../../../artifacts/gte-decoder-native-preparation-20261002/verification.json)
binds current outputs, original artifacts and preserved planning-document
generations. Production optimizer, native-model and KD execution remain zero.

## Source-only evaluation coverage

The [decoder source comparison](gte_decoder_source_evaluation.md) separately
admits all 60 original V2 validation vectors and both original 8D diagnostics.
It joins their native receipts from the complete cache, independently of the
selected 18-row training batch. A ready training batch can leave all primary
validation inputs missing; those missing rows remain in evaluation coverage.
Original donor baselines run from unchanged old vectors while native inputs
are unavailable. No validation reference enters training or generated prefixes.
