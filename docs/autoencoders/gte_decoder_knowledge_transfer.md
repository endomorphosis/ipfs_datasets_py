# Transfer learned decoder knowledge before training the new interfaces

The 768D student starts with the learned 8D and 384D decoder tensors. It does
not start with randomly initialized decoder bodies. This stage prepares the
donors' original cached training inputs, verifies that the copied heads preserve
their token distributions, and exports those distributions for later
distillation. Exact compatible weight copying preserves knowledge immediately;
logit distillation maintains that behavior as the new interfaces and later
capacity begin to learn.

The two new connections still need training: the 768-to-384 input adapter and
the shared-condition-to-8 connector. Copied decoder behavior alone cannot align
these new input spaces. Keep those connections, learned heads and donor models
separately identified throughout the experiment.

The next [native input preparation](gte_decoder_native_inputs.md) joins these
saved targets to exact cached 768D receipts after auditing all original sources.
Its reference objective sends gradients through both new connections with the
inherited heads frozen. Missing receipts stay explicit source-only tasks.

## Faithful cached inputs for each donor

The selected 384D decoder's original V2 Legal archive contains 180 training and
60 validation rows. Every reference fits its exact 32-entry typed-JSON codec,
with 40 tokens including BOS/EOS and 39 next-token positions. The preparation
authenticates the complete original training manifest before selecting a bounded
cohort of training rows. It reuses the same cached 384D arrays and applies the
saved input transform exactly once.

The current V3 migration cohort has 360 Legal training and 120 validation rows.
None of their complete references fits this selected donor's vocabulary: new
actors, actions and objects include custodian, retain, certificate and filing.
These vectors remain useful for vector alignment, but they cannot supply this
head's reference-prefix training until an explicit vocabulary migration. Do not
replace unknown tokens, silently change a codec or call V3 references compatible.

The learned 8D head uses its own 18-entry grammar codec and two original authored
synthetic examples, reports and notices. The saved sample embedding is not its
raw decoder latent. Its frozen initial pairwise projection reconstructs that
latent from the existing cached input:

~~~text
latent_pair = [0.02 * left + 0.1 * right,
               0.02 * right - 0.1 * left]
~~~

Both reconstructed latent digests match the archived inference receipts. The
complete reconstructed training manifest matches the learned head checkpoint's
training hash. This requires no encoder or core execution and does not generate
new semantic embeddings. These exact two inputs remain explicitly synthetic;
the unrelated 58-row linguistic caches use different coordinates and do not
enter this head's replay.

Each grammar reference encodes to 16 tokens, giving 15 next-token positions.
The heads retain independent vocabularies, prefixes, normalization and row
identities. Test/canary data never enters the transfer export, and validation
remains outside this first replay cohort.

## Replay and distillation target exports

The dependency-free
[batch contract](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_batch.py)
checks donor identity, full original input manifests, exact codecs and target
prefixes before numerical loading. Each selected row retains source, input,
reference and prefix digests, shifted labels and an explicit reference mask.
Production KD masks remain false because these donors have no independently
qualified semantic scope. No qualification hash is fabricated.

The [numerical exporter](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_replay.py)
loads independent private donor models and the inherited student. It compares
projected coordinates, conditioning states and all reference-prefix logits for
each head. It also verifies exact parameter values, independent storage and
unchanged state. Output distributions are detached CPU float32 arrays with
separate codec, source and prefix bindings.

The independent 8D comparison loads the original checkpoint into the faithful
private grammar port. Its parameters are separate from the student's copied
parameters; this replay does not execute the full archived 8D application.

The primary replay explicitly supplies its original raw 384D input to the copied
projector and conditioner. The 8D replay supplies its original reconstructed raw
latent to the copied grammar body. These are donor-input replay paths: neither
exercises the new adapter or auxiliary connector, and neither supplies a native
768D input. They establish decoder knowledge preservation, not end-to-end
multilingual performance.

Diagnostic KL compares the copied head with its independent donor on the same
input and reference prefix, using temperature 2. Identical logits have zero KL;
that is the expected result of correct inherited initialization. A zero
preservation loss gives no learning signal for the unexercised interfaces.
Reference-prefix exports are training artifacts and cannot be used as
source-only inference or free-running fidelity evidence.

## Preparation command

The [command](../../scripts/ops/autoencoder/prepare_gte_decoder_transfer.py) binds
all original checkpoint, initialization, input and source implementation bytes.
The [configuration](../../configs/autoencoders/gte_decoder_transfer_preparation_v1.json)
selects at most 16 rows per head. Both complete manifests are checked before
selection; rows are then selected by sorted ID. The hard ceiling is 64 rows per
head, with existing 512/64 prefix limits and a 16 MiB replay-output ceiling.

From the repository root, use a fresh output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_decoder_transfer.py \
  --config configs/autoencoders/gte_decoder_transfer_preparation_v1.json \
  --expected-config-sha256 37b9d9356800429c12358b3844051f58cd40cc15d04cf8b0acf7d4817eacf71b \
  --threads 1 --memory-limit-mib 16384 --cpu-time-limit-seconds 120 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-decoder-transfer-preparation-20261002/reproduction-01
~~~

The command writes the batch, donor bindings, replay exports, resource receipt,
summary and completion manifest. It authenticates saved batch/replay bytes and
inspects their bindings again before completion. Input, donor source and
implementation namespaces are protected. No optimizer is created, no weights
are updated and no encoder or download is invoked.

## Training sequence after this initialization

1. Keep both inherited decoder bodies frozen and retain this behavior baseline.
   Preserve the original donor snapshots and the independent 8D/384D lanes.
2. Reuse existing native 768D receipts, encoding only missing exact source inputs.
   Initially use references supported by the inherited codecs. Prepare a
   separate audited V2-native cohort when fitting this selected 384D donor;
   current V3 vector alignment alone does not make its references compatible.
3. Fit the 768-to-384 boundary on training pairs, select on validation, and load
   the separately identified aligned student. Train the auxiliary connector on
   its matched supported references or properly bound original 8D latent targets.
4. Authenticate a qualified teacher scope and screened supervision for each head.
   Combine reference CE with separately normalized temperature-scaled masked KL.
   Native student logits must come through the new interfaces; losses must
   reach the shared input adapter. Match teacher exports by exact source and
   prefix identity. Keep the encoder frozen initially.
5. Measure free-running reconstruction and logical-field errors, then selectively
   unfreeze inherited tensors at a lower learning rate. Vocabulary expansion
   creates a new codec/checkpoint generation and needs an explicit token mapping
   and supervision contract. The current KL helper requires identical codecs;
   it cannot silently compare expanded and original vocabularies.
6. Promote the learned conditioner and expand context toward 8192 input tokens
   after the applicable fidelity checks. A fresh decoder remains an optional
   ablation. It is not the starting point for the production transfer path.

The [decoder reuse guide](gte_decoder_reuse.md) gives the architecture and loss
ordering. The [cache reuse guide](gte_embedding_reuse.md) preserves the existing
assets and embeddings. Weight transfer, numerical preservation, optimizer-based
distillation and semantic qualification remain separately measured outcomes.

## Measured cached-input replay

The [completed run](../../../../artifacts/gte-decoder-transfer-preparation-20261002/run-01/manifest.json)
used the saved dual-donor initialization, existing embeddings and original
references. It preserved all 26 inherited tensors and the complete student
state. Both copied heads matched their independently loaded donors exactly:

| Head | Original training rows replayed | Next-token positions | Exported logit values | Maximum projected / condition / logit error | Diagnostic KL, T=2 |
| --- | ---: | ---: | ---: | --- | ---: |
| 384D primary | 16 of 180 | 624 | 19,968 | 0 / 0 / 0 | 0 |
| 8D grammar | 2 of 2, synthetic | 30 | 540 | 0 / 0 / 0 | 0 |

The saved [batch](../../../../artifacts/gte-decoder-transfer-preparation-20261002/run-01/batch.json)
and [teacher distributions](../../../../artifacts/gte-decoder-transfer-preparation-20261002/run-01/replay.json)
were authenticated and inspected again after serialization. The completion
manifest binds the original inputs, donor implementations, current helper code
and output bytes. This gives the future trainer a verified learned decoder
baseline and reusable targets. Neither new interface was exercised or fitted;
there were zero optimizer steps and no encoder execution or KD training.

The focused suite passed **303 checks in 157.23 seconds**: 151 new batch,
numerical replay and command checks, plus 152 retained distillation and
dual-donor initialization checks. The
[test receipt](../../../../artifacts/gte-decoder-transfer-preparation-20261002/tests-01/result.json)
records the command and log hashes. The
[verification receipt](../../../../artifacts/gte-decoder-transfer-preparation-20261002/verification.json)
also binds prior artifacts and preserved planning-document generations.
