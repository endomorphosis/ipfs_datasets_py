# Numerical head for compact LegalIR content

This opt-in engineering profile connects the existing numerical GRU to the qualified ordered 537-token compact-content codec. It uses CPU float32 and an explicit 384-coordinate conditioning vector. It introduces no new AST, grammar, embedding producer or legal semantics.

The canonical owner is `logic/formalization/autoencoder/legal_compact_content_head_v1.py`. The earlier flat-rule trainer and its public checkpoints remain separate contracts. The new checkpoint identifies its own task/profile, exact ordered vocabulary and hash, 512-total-ID output ceiling, dimensions, dtype, implementation sources, Torch version and all 13 model-state tensors.

The public API creates or warm-starts a snapshot, hashes it, validates it by strict restore, serializes it, loads independently committed raw bytes, and scores a supplied prefix:

- `create_compact_content_head_v1(*, config=None, parent_checkpoint=None, expected_parent_sha256=None)`.
- `compact_content_head_sha256(checkpoint)`.
- `validate_compact_content_head_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `compact_content_head_bytes_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `load_compact_content_head_v1(checkpoint_raw, *, expected_raw_sha256)`.
- `score_compact_content_head_v1(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256, expected_context_sha256)`.

## Geometry and inputs

The model reuses `modal_latent_formula._model`: a residual projection, conditioning layer, token embedding, single-layer GRU and output layer. Input and projected output each have 384 coordinates. Projection width, GRU hidden width, token embedding width, vocabulary size and total output length are recorded separately. The residual bypass means projection width is not a demonstrated compression bottleneck.

A supplied conditioning vector is a numerical observation. Width and a checkpoint hash do not verify the embedding producer, source geometry, context permission or lawful source interpretation. Raw text and target-derived signature/role context do not become neural inputs in this profile. The symbolic context is supplied separately for the existing prefix constraints and selector only.

Score intake accepts a supplied prefix rather than an expected answer or identity sidecar. For an admissible nonterminal prefix it computes real model logits and calls the existing public finite-score selector. Its report retains all 537 scores, raw/selected decisions and offered/resulting prefixes. A terminal or blocked prefix records an explicit disposition without fabricating a numerical forward. No generation loop, complete target prediction, decoding accuracy or speed comparison follows from a single-step forward.

## Weight identity and restoration

Seeded construction is explicit. An optional warm start first validates the supported trained 384D parent through its existing owner, preserves the parent's compatible geometry and delegates exact transfer to the existing transfer owner. The transfer ledger identifies ten copied nonlexical tensors and three vocabulary-dependent tensors. Shared lexical rows map by exact token spelling; unseen rows use the parent row mean. Mean initialization does not establish learned symbol meaning. The donor remains unchanged. Its expected canonical checkpoint hash uses the existing parent owner’s `checkpoint_digest` convention; the new head’s UTF8 canonical identity and received raw-byte identity remain separate.

The new checkpoint is weights-only. Parent optimizer moments and training examples are not imported. A later training consumer must create a fresh optimizer and bind its actual data/eligibility contract. Trained weights and optimizer progress require a separately versioned checkpoint contract; they cannot be relabelled as this zero-step v1 snapshot. This profile does not provide optimizer resumption, a training API or compatible loading of arbitrary historical lineages. The separately qualified native4096 source-span consumer's Adam resumption remains evidence for that different grammar and input contract.

Restoration checks the whole closed checkpoint: ordered vocabulary/task/profile/output ceiling, metadata commitments, every tensor name and shape, exact exported float32 values, finite conversion and implementation binding. Integer tensor leaves and doubles that would round to a different float32 value are refused. Wrong dimensions, extra state, bools, nonfinite values and overflowing finite doubles are refused. No partial tensor installation is a successful restore. Canonical checkpoint identity and received raw-byte identity are separate commitments.

Numerical operations require the caller's admitted CPU scope and one Torch thread. Construction uses the existing locally seeded RNG-preserving mechanism. A numerical restore requires the checkpoint’s recorded Torch version to match the installed version. This version guard does not authenticate binaries. Installed Torch and NumPy are third-party runtime dependencies; source fences and test-child raw compilation do not prove their binary provenance or a hermetic operating system.

## Qualification scope and remaining work

Engineering tests use fabricated conditioning and explicitly authored targets. A tiny old-grammar parent fixture may perform one real CPU update solely to test validated transfer from a trained donor. This compact head performs zero new-target optimizer updates. Real logits and exact state/logit reload checks qualify mechanics, not source-held-out performance or legal meaning.

All source/review/training/gold authority remains false and eligibility masks remain zero. Source occurrence/cache joins, interpretation and governing definitions, permitted context, producer binding, exposure/splits and complete-population consumer eligibility remain required before statutory fitting or evaluation. Reuse the current qualified semantic-token batch/reconstruction owner rather than making another denominator.

[Implementation evidence](../../../../../../../artifacts/legal-ir-compact-numerical-head-20261017-01/README.md) records exact API/report schemas, source generations, numerical diagnostics and owned resource closeout.

**Public counted extension boundary:** the appended sections document four existing owners: `ir_decoder_profile_inventory`, `legal_counted_content_head_v1`, `legal_counted_content_head_transfer_v1` and `legal_counted_threshold_numerical_view_v2`. The original public537 guide above is preserved byte-for-byte. The separate [symbolic counted guide](legal_counted_frame_v1.md) retains its own fixed-three/three-form codecs and prefix route. No companion/source-join/review extension, private observer, checkpoint, raw run or model asset is supplied by this source bundle. Historical qualification scopes remain separate; this publication performs no new test, numerical forward, training, encoder or Lean operation. The [portable evidence ledger](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) records source-generation comparison and the declared limits. The original artifact link above remains a historical locator, not a promise that raw artifacts are included.

## Declared counted28 head specification

The existing numerical metadata owner
`logic/formalization/autoencoder/ir_decoder_profile_inventory.py` has a separate
`legal-counted-content-head-spec/v1` contract. It describes the layout required
by the selected counted28 codec. It creates no checkpoint, model, tensor,
optimizer, registered runtime or additional decoder cell. The original twelve
inventory cells, Intent/Security checkpoint registration and LegalIR4096 source
representation profiles retain their existing contracts.

This specification is separate from the 537-token head described above. Its
factory calls that head's existing pure `_shapes` declaration and changes only
the first dimension of `target_embedding.weight`, `output.weight` and
`output.bias` from 537 to 28. The other ten declared shapes remain identical.
The old head, token, selection and source-conditioning owners are unchanged;
existing 537-token checkpoints are neither loaded nor relabelled.

```python
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_profile_inventory as profiles

codec = counted.build_counted_frame_token_codec_v1()
# Use an independently retained codec commitment, rather than taking an offered
# report's expected hash as authority.
spec = profiles.build_counted_content_head_spec_v1(
    codec,
    expected_codec_sha256=retained_counted_codec_sha256,
    config={"hidden_size": 32, "token_embedding_dim": 16, "projection_width": 16},
)
profiles.validate_counted_content_head_spec_v1(
    spec,
    codec,
    expected_spec_sha256=independently_retained_complete_spec_sha256,
    expected_codec_sha256=retained_counted_codec_sha256,
    config={"hidden_size": 32, "token_embedding_dim": 16, "projection_width": 16},
)
```

The complete spec hash comes from `counted_content_head_spec_sha256(spec)`.
Hashing bounded metadata grants no compatibility or model authority. Validation
requires independently retained complete spec and codec pins, then regenerates
the spec from the complete original codec and original geometry declaration.
A different valid geometry describes a different specification; it is not a
checkpoint migration.

The selected codec is the existing counted owner's exact ordered vocabulary,
with canonical SHA256
`8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8`.
It has 28 entries, PAD/BOS/EOS at 0/1/2 and a 512-total-ID ceiling. The selected
wire format retains literal sort names such as `EventFrame` and `TimeFrame`.
An unqualified sibling using sort indices is incompatible despite reusing
schema labels. Neither the normative32 nor the Object-only 537-token codec is
accepted by the spec factory.

Geometry accepts only the three plain integer fields above. `hidden_size` is
8–128, `token_embedding_dim` is 8–64 and `projection_width` is 1–64; omitted
fields use 32/16/16. Seeds, model states, checkpoints, training corpora, source
vectors, original targets and identity sidecars are not factory inputs. The
default layout declares 31,180 parameters and 124,720 bytes at float32. Those
figures are shape arithmetic, without allocating or verifying any tensor.

The input-space declaration is specifically 384-entry raw native GTE-small,
using the existing receipt-reuse schema/profile, fixed model revision and
asset-manifest identity. The completed two source-conditioning preparations
remain separate evidence. This metadata factory neither repeats them nor
authenticates source bytes, vectors, model execution, permission to use context
or compatibility with a fitted head. Shape 384 alone does not identify that
space; raw, core and trained representations remain distinct.

The factory preflights ordinary bounded inputs and independently pinned codec
bytes before lazy operation imports. It checks the known canonical counted
and old-head source paths against reviewed hashes, validates imported owner
origins before public calls, and fences caller/detached inputs and producer
sources through final serialization. The public counted codec is regenerated
and compared in full. These are sequential named-source checks, not executed
bytecode attestation, a lock or a hermetic runtime.

`runtime_compatible`, `tensor_shapes_verified`, `checkpoint_compatible`,
`prefix_api_available`, `permitted_source_only_context` and
`varied_reviewed_targets_supplied` remain false. All authority flags remain
false and training/evaluation-gold masks remain integer zero. The original
fixed-three codec supplies complete archival transport, not a numerical API.
The separate published three-form symbolic prefix route and the numerical
profiles below retain their own contracts; this specification supplies no
scorer or generation loop. One fixed authored counting fragment is also
insufficient to establish learned dependence on source text. A varied reviewed
target population, permitted source-only context and qualified input-space
training/runtime compatibility remain required. No model training, convergence, legal meaning or Lean admission is
established by this specification.

The declared specification and its owning controls have the separate closed qualification below. That engineering result leaves the compatibility and semantic limits above unchanged.



### Counted28 metadata transfer plan

The same inventory exposes `plan_counted_content_head_transfer_v1`, `counted_content_head_transfer_sha256` and `validate_counted_content_head_transfer_v1`. They regenerate a possible ten-nonlexical/three-lexical transfer from an independently pinned complete spec/codec and caller donor declaration; they open no donor tensor or checkpoint and allocate no model. Declared shared rows and donor means are requests, not an actual transfer result. The separately retained metadata qualification is **79 cases / 237 phases**: 52 peer-spec controls, 24 transfer-plan controls, two source4096 controls and one private observer. That observer and the historical companion are not published unit cases or new executions here. The [portable evidence ledger](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) keeps this metadata-only result separate from the numerical cohorts below.

## Closed counted companion/spec qualification

**Historical companion/spec evidence:** the following249-case generation includes a separate primary-only companion and actual §7214 observer. This four-owner source publication does not deliver those consumers or replay that cohort.

The [closed qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) passed all 249 cases: 59 original companion regressions, 97 original numerical-inventory regressions, 40 new companion controls, 52 new head-spec controls and one retained §7214 integration observer. Both unchanged source-only input custody and separate counted labels replay through genuine owners. The retained counted projection and293IDs match exactly. The default spec declares13shapes and31,180parameters/124,720float32bytes; these are arithmetic declarations, without allocating tensors.

Original native/storage/source READ closed. Prior170/275-case and native-conditioning operations were reused without another campaign. The exposed/unassigned actual example retains no embedding reference. All prior35 review obligations remain unresolved, and target-derived context remains label-only. No numerical head/checkpoint/runtime, prefix scoring, independently permitted conditioning, reviewed complete target population, model execution, learning/gold, statutory meaning, convergence or new Lean build is qualified. The original537token/head implementations remain byte-identical.

These 249 passes qualify the frozen source generation. Two shared metadata owners gained append-only BOS-preflight APIs after its source READ closed; their observed original prefixes and function/class ASTs remain unchanged. The [bounded post-close observation](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) describes those additions and supplies no qualification for the newer APIs.
## Seeded counted28 numerical adapter

A separate versioned owner,
`logic/formalization/autoencoder/legal_counted_content_head_v1.py`, adapts the
existing numerical machinery to the selected counted28 codec. It reuses the
unchanged fixed537 head's bounded checkpoint/restore helpers, the existing
residual-projection GRU kernel, the declared counted28 specification and the
counted owner's complete decoder. It changes no legacy checkpoint, codec,
inventory or prefix grammar. This section describes the exact historical
qualified source generation; publishing it is not a new numerical run.

The owner exposes seven APIs:

- `create_counted_content_head_v1(*, config=None)`.
- `counted_content_head_sha256(checkpoint)`.
- `validate_counted_content_head_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `counted_content_head_bytes_v1(checkpoint, *, expected_checkpoint_sha256)`.
- `load_counted_content_head_v1(checkpoint_raw, *, expected_raw_sha256)`.
- `score_counted_content_head_v1(checkpoint, conditioning, prefix_ids, *, expected_checkpoint_sha256)`.
- `evaluate_counted_content_head_v1(checkpoint, conditioning, target_ids, context_raw, *, expected_checkpoint_sha256, expected_context_sha256)`.

The snapshot profile is `seeded-counted28-content-head-384/v1`. Construction is
fresh, locally seeded, CPU float32 and zero-step: no counted optimizer update,
donor transfer or optimizer state. The separate checkpoint commits its codec,
specification, implementation generation, geometry, seed, Torch version, all
thirteen model-state tensors and weights hash. Validation and byte loading
require complete independently pinned metadata and strict finite float32
restoration. Canonical checkpoint identity and received raw-byte identity stay
separate. Hashing a bounded offered value alone does not validate a snapshot.
Numerical calls require the existing admitted one-thread CPU execution scope.

The actual input role is
`unverified_caller_supplied_conditioning_vector`. Its 384 coordinates do not
satisfy the specification's separately retained `raw_native_gte_small384`
expectation by declaration. The engineering fixture deliberately uses a
fabricated sparse vector: first coordinate 1.0, the other 383 coordinates 0.0.
It is no source embedding, native encoder receipt or conditioning-space
compatibility result. No target-derived counted context is put into that
vector, and no correspondence to the retained native heading inputs is claimed.

Raw scoring takes a nonterminal list with BOS first, followed only by in-range
lexical IDs, with fewer than 512 total IDs. That token-range/framing check is
**not grammatical prefix acceptance**: an in-range prefix can be impossible in
the counted language. Scoring has no reference target or context argument. It
returns all 28 last-position logits and raw argmax, with no grammar mask,
allowed-next-token selector, EOS repair or generation loop. PAD/BOS/EOS remain
possible raw model predictions; recording a logit does not make it admissible.

Teacher-forced evaluation first sends the complete offered target and separately
pinned context to `decode_counted_frame_tokens_v1`. Only a genuinely accepted
complete fixed-language sequence reaches the numerical forward. The retained
fixture has 293 total IDs: inputs are `target_ids[:-1]`, labels are
`target_ids[1:]`, and the resulting 292 by 28 logits remain unmasked. All 292
prediction positions contribute to ordinary 28-way cross-entropy, including
terminal EOS. BOS supplies the first input; it is not a label, and no padding
or singleton grammar mask removes alternatives from the loss. Target tokens
are exposed as teacher-forced history; the target-derived context is used for
label validation and does not enter the neural conditioning vector.

Loss, teacher-forced token matches, raw EOS positions and strict reload
agreement are numerical engineering observations. They are neither autonomous
sequence generation nor source-held-out accuracy. The original fixed-three
codec admits one content/context pair: a constant output can complete it without using prose,
and a singleton grammar mask would make every valid next-token choice forced.
The retained US Code companion remains an exposed, unassigned partial authored
label with no embedding reference, unresolved review obligations and integer-zero
training/evaluation-gold masks. It supplies no varied reviewed target population,
independent counted-context permission or complete statutory norm.

No trainer, generation/serving route, donor checkpoint consumer, optimizer
resume, source-to-model equivalence, learning, legal meaning or Lean admission
is supplied by this adapter. Existing 8D, 384D, 768D and genuine4096D contracts
retain their own producers and qualifications. All authority fields remain
false and eligibility masks remain integer zero.

The [closed numerical qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) passed **46 cases / 138 phases**. The genuine existing CPU GRU produced all292 unmasked28-way score rows for the exposed authored target. The admitted configuration uses hidden8/embedding8/projection4, seed1729 and7,448 actual parameters with384 input coordinates. Its untrained baseline cross-entropy is3.2525432199783406, with11/292 raw teacher-forced token matches and no complete sequence match; this is not statutory accuracy. Independent Torch cross-entropy agrees, including terminal EOS; exact weights and logits survive independent JSON restore. Changed fabricated conditioning changes raw scores. Original source/native/storage custody closed. The unlaunched stale snapshot and earlier zero-case pytest logging failure remain separate preserved generations; the retry changes only the owned log path. No training, optimizer update, donor transfer, model-asset load, autonomous generation, reviewed statutory accuracy or Lean execution occurred. The earlier249-case metadata/companion and79-case transfer qualifications retain their separate generations.
## Counted28 donor transfer adapter

The separate owner
`logic/formalization/autoencoder/legal_counted_content_head_transfer_v1.py`
consumes an original, independently pinned 537-token compact-head donor and
reuses the existing counted28 metadata transfer plan. It keeps the original GRU
kernel, fixed537 head, counted codec/specification and seeded counted-head
implementation unchanged. The seeded owner's qualified source generation is
`b51d003f99c2cc889776509bbda165477833bb09ee327da8549bc6d17169e4e6`.
Its distinct profile is `validated537-to-counted28-content-head-384/v1`;
a transferred snapshot is never presented as a seeded-v1 checkpoint. This
section records the qualified frozen donor-transfer source generation below.

The five public APIs are:

- `create_transferred_counted_content_head_v1(donor_checkpoint, *, expected_donor_sha256)`.
- `transferred_counted_content_head_sha256(checkpoint)`.
- `validate_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, *, expected_checkpoint_sha256, expected_donor_sha256)`.
- `score_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, conditioning, prefix_ids, *, expected_checkpoint_sha256, expected_donor_sha256)`.
- `evaluate_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, conditioning, target_ids, context_raw, *, expected_checkpoint_sha256, expected_donor_sha256, expected_context_sha256)`.

Hashing a bounded offered value alone does not validate its transfer.
The original 537-token donor and its independent checkpoint commitment remain
required for restoration, scoring and evaluation. A resealed transfer ledger or
an embedded donor hash cannot replace genuine replay through the original donor
owner and full comparison against its actual tensor values.

The existing plan distinguishes ten compatible nonlexical tensors from three
lexical tensors. It maps shared rows by exact ordered token spelling and requests
original donor lexical-row means for new spellings. Actual copying and row means
must be observed on the complete tensors; the metadata plan alone supplies no
transfer result. Preserve canonical checkpoint versus raw-byte identities,
complete source/codec/specification commitments, tensor shapes, Torch version,
actual donor lineage and a fresh optimizer requirement. The principal 537-to-28
adapter imports no donor optimizer moments and executes no optimizer updates.
The separate retained-ancestor observer uses the original old-modal-to-537
factory, whose public validation necessarily constructs/restores historical
Adam state and moments. That restoration performs no new optimizer step; it is
not performed by the 537-to-28 adapter. Do not describe the whole observer
cohort as having no optimizer construction or restoration. A genuine
retained-parent-to-537 lineage remains evidence for its original task and
source generation; it does not become counted training, legal meaning or
compatible conditioning by reuse.

The actual numerical input remains an unverified caller-supplied 384-vector.
The separately declared raw native GTE-small384 target space is not established
by equal width, donor lineage or a successful restore. Fabricated conditioning
stays an engineering fixture. Old native heading inputs, normalized operative
source occurrences and target-derived counted context retain separate custody;
no new correspondence is supplied here.

Raw scoring must expose all 28 logits. BOS/lexical range checks are not grammar
acceptance, and no singleton mask or selector can be credited as learning.
Teacher-forced evaluation must reuse complete counted decoding and keep context
as label-only information. For the retained 293-ID target, inputs omit final EOS,
labels omit initial BOS and all 292 unmasked 28-way losses include terminal EOS.
Compare donor and transferred observations only with their exact declared
profiles; a change in exposed singleton loss is not source-held-out accuracy.
There is no generation loop, trainer, optimizer resume or new statutory target
admission. Training/evaluation-gold masks remain integer zero and source/review
and proof authority remain false.

The [closed donor-transfer qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) passed **39 cases / 117 phases**. The principal38-case scope uses a newly seeded public537 donor and forbids optimizer construction. Genuine domain384 transfer copies ten nonlexical tensors bit-for-bit and maps23 shared spellings plus five full537-row means across each of three lexical tensors. Complete donor-required JSON replay preserves all13 tensor states and raw logits; the independent Python log-sum-exp oracle agrees with the unmasked292-token teacher-forced loss. Changed fabricated conditioning changes raw scores. The separate retained-ancestor observer enrolls exactly one original historical Adam construction and restoration of13 moment entries at original step1, with zero new optimizer updates, zero backward calls and zero new compact/count28 training steps. The three diagnostic arms have exposed singleton cross-entropy 3.1629002519970832 for newly seeded537-to28 transfer (36/292 raw teacher-forced token matches), 3.3621639375092434 for retained-parent transfer (0/292), and 3.2525432199783406 for seeded counted28 (11/292). The retained-parent loss is higher than the seeded counted28 baseline; the newly seeded537 transfer loss is lower than that baseline. These are initialization and vocabulary-transfer diagnostics, with no counted training gain established. This comparison uses fabricated sparse384 conditioning, target-derived label-only context and all292 unmasked28-way scores including terminal EOS; it supplies no source-held-out or statutory accuracy. Original source/native/storage custody closed. Existing seeded numerical, metadata-plan and peer qualifications retain their own source generations. No trainer, generation loop, optimizer resume, conditioning compatibility, reviewed statutory target, training/gold or Lean admission is supplied.

### Seeded three-form numerical vocabulary view v2

The separate owner `legal_counted_threshold_numerical_view_v2.py` exposes a
fixed vocabulary view of the existing seeded counted28 checkpoint. Its profile
is `seeded-counted28-three-form-vocabulary-view-384/v2`, with metadata schema
`legal-counted-threshold-numerical-view/v2`. It reuses the unchanged seeded
checkpoint validator, strict CPU float32 restoration and original GRU forward.
It does not create or rewrite a checkpoint, modify weights, initialize a new
row, transfer donor tensors or add an optimizer, trainer or generation loop.

The four public APIs are:

- `build_counted_threshold_numerical_view_v2()`.
- `counted_threshold_numerical_view_sha256(view)`.
- `score_counted_threshold_numerical_view_v2(checkpoint, conditioning, prefix_ids, *, expected_checkpoint_sha256, view, expected_view_sha256)`.
- `evaluate_counted_threshold_numerical_view_v2(checkpoint, conditioning, target_ids, context_raw, *, expected_checkpoint_sha256, expected_context_sha256, view, expected_view_sha256)`.

The view is fixed metadata independent of any checkpoint. Building/hashing it
constructs and restores no model. Its complete content is regenerated and
byte-compared on every use, so resealing an alternative mapping supplies no
permission. The declaration retains original and successor codec commitments,
implementation hashes, exact lexical rows, authority flags and limitations.
Each numerical result separately binds the original checkpoint/weights/profile,
old model codec, successor observation codec, view and conditioning commitment.
A metadata view alone does not attest strict numerical restoration or runtime
Torch compatibility; the existing owner checks these during the actual forward.

For 27 exact token spellings, an observation token uses the matching original
model row. The new content-schema token explicitly uses the old content-schema
row under `explicit_schema_role_relabel`; it is not an exact spelling copy,
learned embedding or row-mean initialization. Both schema literals sort to
row 10, and the actual mapping is the identity on all 28 numeric IDs. No
nonidentity permutation is demonstrated. The adapter translates prefix IDs
and returns all old logit columns in successor vocabulary order, leaving the
original checkpoint, codec/specification and all 13 tensor states intact.
Equal numeric IDs do not make the two content/codec schemas identical or grant
checkpoint/semantic compatibility.

Only the original seeded counted28 profile is accepted. The distinct
537-to-counted28 transferred snapshot still requires its original public537
donor and genuine donor-aware validator, and is outside this consumer. Prior
transfer diagnostics, including their separately enrolled historical Adam
restoration, retain their exact original scope and are not rerun by this route.

Raw scoring takes a caller 384-vector and a nonterminal BOS/lexical prefix,
with no complete target, context or chosen cap. It returns all 28 last-position
logits, including special-token columns, and a raw argmax. Range/framing checks
are not grammar acceptance, and no allowed-token mask, target selector or
finite-language completion is applied. A later generation consumer must state
its grammar assistance separately from the raw numerical predictions.

Teacher forcing first invokes genuine public three-form complete decoding on
the offered target IDs and independently pinned exact common context. Invalid
labels cannot initiate model construction or forward. It then reuses one
strict old-checkpoint restoration and one actual forward per evaluation,
feeding the mapped target without final EOS and scoring labels without initial
BOS. The three forms have 116/194/292 unmasked 28-way positions, including EOS.
Standard Torch float64 cross-entropy observes the exported float32 logits; all
logits, per-token losses, raw predictions/matches and complete-decode commitment
are retained. Report per-form engineering diagnostics separately, without
crediting exposed target differences or an aggregate loss as training gain.

The common cap-free context validates authored labels only and never enters
the conditioning vector or GRU. Actual input remains an unverified caller
384-vector; equal width does not establish the separately declared raw native
GTE-small384 expectation or source correspondence. Source headings, operative
occurrences, authored targets and permitted inference context retain separate
custody. All source/review/proof/checkpoint-compatibility flags remain false,
training/evaluation-gold masks remain integer zero and no source dependence is
established.

Qualification: The [closed qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-numerical-publication-20261023.json) passed **46 cases / 138 phases**, all focused numerical-view cases; no legacy whole campaign was rerun. The same unchanged seeded checkpoint supplies three complete 116/194/292-by-28 unmasked teacher-forced observations including EOS. Actual per-form diagnostics: limit 1: CE 3.2715484464624036, 3/116 raw token matches; limit 2: CE 3.2540739577967495, 7/194 raw token matches; limit 3: CE 3.2525432199783406, 11/292 raw token matches. Each principal public evaluation records one strict host restore and one GRU forward; independent host/CE test oracles execute additional calls outside that instrumentation scope. Direct original-host logits match exactly and independent saved-logit cross-entropy agrees. The 13 tensor states, checkpoint/weights identities and CPU RNG are unchanged; 27 spellings match and one row 10 schema marker is explicitly relabeled, with an identity numeric map and no new row, checkpoint, transfer, optimizer, backward/update or generation. Changed fabricated conditioning changes raw scores; these are exposed authored-label diagnostics with no learning gain, source-held-out or statutory accuracy. The 483-byte common context remains unreviewed label validation only. All authority flags remain false and masks integer 0. Original source/native/storage custody closed.

The adapter preserves original/captured caller inputs and checks its
adapter/seeded-host/codec sources immediately before forward and after host
serialization, including exceptional closing paths. Existing host/kernel
closures retain their own source/input custody; genuine successor decoding
fences its semantic-owner call. These named checks do not constitute an
independent full raw-execution, loaded-bytecode or third-party binary attestation.
No backward/update, optimizer resume, reviewed-law training, graph admission or
new Lean artifact follows from this numerical observer.

### Next target-language task

The [qualified three-form codec/prefix route](legal_counted_frame_v1.md#three-form-threshold-codec-and-prefix-v2)
retains its own [81-case / 243-phase qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-threshold-publication-20261023.json).
The numerical view above adds a separately scoped seeded-weight observer;
it preserves the old singleton checkpoints and admits no new training data.
Target-independent numerical generation, any grammar-assisted selection and
complete successor decoding still need their own consumer contract and
qualification. Keep raw predictions, syntactic completion and exposed
teacher-forced diagnostics distinct.

Prepare independently authored prose and source-only context that keep caps,
target trees and cap-derived binder information outside inference inputs.
Use paired limits, grouped held-out paraphrases and constant/shuffled-label
controls to test dependence on the offered text. Preserve source, edition,
dependency, exposure and competing-interpretation groups; three distinct
labels do not constitute three reviewed laws. A trainer additionally needs
explicit eligibility/exposure and checkpoint/optimizer contracts, an admitted
objective and independently reviewed evaluation targets.

Actual US Code work still needs reviewed varied targets, counting units/frames,
governing definitions, edition/applicability, permission/purpose/anaphora,
permitted context and genuine source-to-vector correspondence. Missing labels
stay null and statutory masks stay integer zero until existing review and
consumer owners supply admission. This observer supplies no learning gain,
autonomous legal-text inference, complete norm, graph or Lean authority.
