# Experimental LegalIR decoder profiles

Six reusable decoder kernels now have one installed experimental home in
`ipfs_datasets_py.logic.autoformal.experimental`. They preserve the unique
LegalIR architecture, state and session contracts from the retained source
proposals. Their shared parent, numerical, compact-content training, grammar and
selection owners remain in `logic.formalization.autoencoder` and
`optimizers.logic_theorem_optimizer`; no generic backend is copied here.

This is an explicit experimental interface. It adds no default checkpoint,
checkpoint-hub lane, provider, upload, training campaign or automatic statutory
admission. Source migration and engineering tests cannot establish legal
meaning, held-out quality, convergence or a reviewed Lean corpus. See the
[migration map](../ARCHIVE.md), [historical pre-installation source proposals](../../../../../docs/autoformalization/proposals/source-proposals.json),
[current handoff](../HANDOFF.md) and [model handbook](../../../../../docs/autoencoders/README.md).
The source-proposals manifest is an immutable historical export: its
`not_started` and `runtime_installed=false` observations describe the original
proposals. Current successor installation and qualification are recorded in the
[work catalog](../work_catalog.json) and the qualification receipt below.

## Modules and contracts

| Module in `logic.autoformal.experimental` | Public operation and preserved boundary |
| --- | --- |
| `projected_context_decoder_v1` | `inspect_parent_source_compatibility` checks authenticated source metadata only; `build_from_real_parent`, `load_with_real_parent`, `model_state`, `infer`: genuine LegalIR384 parent, exactly 13 tensors, token16 followed by projected384 in a GRU input of 400. Initialization copies 12 complete tensors plus the original GRU columns and zeros only the added columns. Target-free inference uses source embeddings and hashes source text as provenance. |
| `trained_projected_context_decoder_v1` | `make_checkpoint`, `load_trained_with_real_parent`, `infer_trained`: separate trained context150 profile, all 13 tensors, four frozen projection tensors, exact parent/initial identities and original 180/60 manifests. Other decoder tensors may change. Auxiliary-head and Adam state are excluded from inference; supplied training provenance is a declaration, not independent execution proof. |
| `gated_conditioning_v1` | `checkpoint_sha256`, `inspect_checkpoint`, `runtime_metadata`, `migrate`, `restore`: fixed compact384 donor, 13-to-15 tensor transition, zero scalar gate and seeded no-bias 384-to-8 projection. Restore reuses the canonical JointDecoder and preserves full-prefix inference. Migration creates no resumable Adam state. |
| `gated_training_state_v1` | `checkpoint_sha256`, `inspect`, `create`, `restore`, `pack`: fixed `h0_only`/`gated_per_step` arms, real named Adam state, fresh optimizer for the new architecture, exact defaults/order and one completed update per `pack`. An inference checkpoint never supplies missing optimizer history. |
| `journal_training_session_v1` | `prepare(checkpoint, *, expected_sha, max_steps=3, checkpoint_cadence=2)`: opaque process/thread-confined session exposing `advance`, `snapshot_numeric`, `checkpoint`, `inspect`, `close` and context management. The hard-three budget is cumulative from the fixed step8 anchors; cadence is exactly two, restore budgets survive resume, mutation poisons the session, and checkpoint durability belongs to the caller. |
| `journal_inference_v1` | `inspect`; `prepare(checkpoint, *, expected_sha, views, expected_views_sha, max_new_tokens=64, resume_state=None, expected_resume_sha=None)`: complete step11 journal profile, model-only restore, fixed fictional retention/inspection rows and target-free serving views. Opaque sessions expose `score`/`score_bos`, `advance`, `generate`, `snapshot_state`, `inspect`, `close`. Full-prefix decoding retains the original BOS64 bound and trace refusals. No optimizer or externally supplied target/prefix is introduced. |

Every module also exposes `source_profile_bridge()`, a detached discovery report
that requires no checkpoint or Torch. Existing operation signatures are
preserved. The context operations still take explicit Torch/source/parity
arguments, but the source and parity arguments must be their fixed genuine
canonical owners. They are not caller validation callbacks. For example:

```python
from ipfs_datasets_py.logic.autoformal.experimental import (
    projected_context_decoder_v1 as context,
    trained_projected_context_decoder_v1 as trained,
)
from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2

bridge = context.source_profile_bridge()  # bounded source metadata only
# An admitted numerical caller authenticates the actual parent/checkpoint files
# and supplies their pinned parsed values to the explicit loader. No asset is
# downloaded or inferred from the discovery report.
```

The domain facade `logic.legal_ir.autoencoder` and its current pinned release are
unchanged. The existing 384D/768D ordered-clause contextual runtime is a different
architecture and state contract; width alone cannot make it a context150 loader.
This port does not pad, truncate, substitute encoders or reinterpret latent width.

## Versioned source and profile compatibility

`_legacy_source_bridge_v1` records the six exact retained source SHA256 values,
byte lengths and historical path suffixes already preserved in
[source-proposals.json](../../../../../docs/autoformalization/proposals/source-proposals.json). Each producer identity
must be one of the registered identities; a recipe need not contain all six.
The original artifact sources, checkpoints, transcripts, receipts and proposal
patches stay unchanged in their original custody.

New context, gated-training-state and journal producer recipes include actual
packaged source identities and `source_profile_bridge_sha256`. Complete legacy
recipes omit that new field and must match their exact registered historical
identities. Mixed legacy/current generations, partial bridge fields, unknown
hashes, changed lengths, extra keys and unsupported path suffixes refuse.
Nested journal recipes obey the same generation rule. There is no mutable
allowlist or caller-supplied compatibility function.

The gated migration is deliberately different: its historical `implementation`
is a list of the existing shared-owner descriptors, not its own producer hash.
That capsule and the fixed migration digest remain unchanged so that retained
gated-state anchors remain meaningful. Its executing packaged source and bridge
are exposed separately by `source_profile_bridge()`. Do not claim that every
newly emitted legacy-format migration capsule carries the new bridge field.

Historical paths in a legacy recipe are **declared producer references**. The
bridge checks their registered suffix, length and hash without opening those
paths. This does not freshly authenticate the original physical source file.
Current package sources are bounded single-link regular files and are rechecked
against identities captured when their modules were imported. New producer
recipes bind the bridge bytes as well. These cooperative source-file checks are
not arbitrary Python reflection or monkeypatch attestation.

Shared-owner hashes and their existing path rules remain exact. The bridge does
not translate arbitrary absolute shared-owner paths, rebind parent assets,
weaken original cohort/anchor hashes, create an optimizer from absent state, or
generalize a fixed journal profile. A retained checkpoint with an incompatible
shared-owner location or unrecognized producer combination explicitly refuses.
Passing the bridge establishes only this declared compatibility policy; original
checkpoint reload/logit parity still needs its own recorded execution evidence.

One continuation is deliberately unsupported. `gated_training_state_v1` can
inspect and restore an exact legacy training checkpoint, but `pack` refuses to
emit new updates from a legacy producer recipe before exporting numerical state.
That legacy profile reconstructs its initial checkpoint digest using the original
recipe: replacing it would sever lineage, while retaining it for a new update
would falsely name the historical producer. New canonical `create`/`restore`/
`pack` flows work under their current recipe. The separately versioned journal
envelope can consume its exact legacy step8 anchors and records the current
producer for new journal outputs. A future general legacy-state continuation
needs another explicit lineage-preserving version, not a relabeled digest.

## Parent source compatibility preflight

`inspect_parent_source_compatibility(source, parent_checkpoint, *,
expected_checkpoint_sha256)` compares the full retained parent implementation
recipe with the genuine current shared source owner before numerical loading.
The expected digest binds the **canonical `source._raw` checkpoint value**;
a physical JSON file hash authenticates different bytes and must be checked
separately by the caller. The preflight accepts only a bounded, plain finite
source-v2 parent envelope, reports exact nested field paths and retained/current
identity values, and leaves the original checkpoint unchanged.

The result uses `legal-ir-parent-source-compatibility/v1` and
`scope=source_implementation_metadata_only`. Even `compatible=true` leaves
`weights_checked`, `tensor_shapes_checked`, `numerical_execution_performed` and
`checkpoint_load_qualified` false. Tensor values, actual weight digests, model
loading and training history remain outside this inspection. The existing
strict parent/loader implementation checks are unchanged; preflight is not a
shared-source compatibility allowlist or an authorization to run a model.

The retained Context150 parent, step-zero and step150 assets were recovered.
Its parent implementation pins two shared owners that differ from the current
checkout inspected on 2026-10-20:

| Shared owner | Retained SHA256 | Inspected current SHA256 |
| --- | --- | --- |
| `logic/autoformal/tree_pin.py` | `587165942fb06ea9effc836b555e0ac0606c5876b013a374a1e76d25ee069e4d` | `ec43fd9379f3c9198451e8d62d98db53826dcf115e6858039a73c3da7d72a1c2` |
| `logic/ui_ux_ir/decoder.py` | `d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57` | `21e8315b0054f7755512212d610d4e3f5f4ac86387f3b27edb9632fa8ca68bc3` |

The tree-pin change redirects its diagnostic to stderr. The UI/UX decoder is a
substantive exact-field/type codec revision, even though LegalIR generation does
not call UI decoding. The complete shared-owner recipe remains bound by the
loader. Do not rewrite the retained checkpoint descriptors, substitute a caller
validator, or silently generalize the six-profile bridge. Current-owner replay
needs a separately declared and reviewed shared-source compatibility/migration
contract. A frozen historical dependency-tree replay would establish archive
reproduction only.

**Preflight qualification:** 31 focused checks and 93 test phases passed against the merged current owning-test file, including the authenticated retained-parent observation and refusal before tensor access. Original source, native-compute and storage releases for this successful cohort are bound by the [qualification record](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-context-preflight-20261020-01/qualification-summary.json). The preflight addition preserves all 18 pre-existing product-function ASTs. That statement applies to product functions: the owning algorithm-preservation test deliberately adds the new public function to its explicit allowlist and is not byte-unchanged.
No model/checkpoint numerical replay is claimed by source inspection.

The retained free-running files preserve per-row candidate IR, termination,
validity and token counts, but no raw logits or complete generated-token lists.
A later target-free engineering replay can compare the retained observations;
it cannot claim historical raw-logit parity from aggregate parity summaries.
Context150's adverse exact-reconstruction result and the choice of the strongest
compatible 384D wording baseline remain separate model-quality questions.

The next compatibility change is a narrowly versioned profile covering the complete **parent → initial checkpoint → trained checkpoint → inference** path. It must bind both retained producer and current consumer identities without relabeling the original parent, initialization or trained state. Existing loaders retain their exact strict checks. Require explicit lineage joins and mixed-generation rejection at each boundary, unchanged finite tensor/state contracts, and bounded retained candidate/termination observations after separately reviewed execution. This is the next implementation plan; this metadata preflight implements no compatibility translation or numerical replay.

## Bounds and ownership

The original limits remain: context checkpoints8MiB; gated migration64MiB;
gated training checkpoints16MiB and populations2MiB; journal checkpoints8MiB,
reports3MiB and partials8MiB; journal serving states8MiB and 64 generated tokens.
The original tensor finiteness, exact float32, parameter-order, scalar-type,
policy, source, RNG, mutation, close and resume checks remain with their kernels.

The producer-metadata bridge additionally bounds ordinary metadata before source
hashing: depth32,10,000 visited nodes,65,536 UTF-8 bytes per string,1MiB charged
scalar content, bounded signed64-bit integers and no cycles, object hooks or
non-plain keys. This is a metadata work bound, not an increase to any checkpoint,
training, native, storage or resource-admission limit.

Canonical installation and numerical validation use the existing source lease,
frozen request and owned-resource validation path. Importing this namespace does
not admit work. Historical controllers, host-specific `training_core.py`, model
weights, datasets, private snapshots and checkpoint payloads remain evidence;
they are not package resources or product entry points.

## Focused qualification scope

The focused test file is
`tests/unit/logic/autoformal/test_legal_ir_experimental_profiles_v1.py`. It checks:

- exact reconstruction of all six pinned portable proposal sources and AST
  preservation of numerical constructors, forwards, restores, exporters and
  journal state transitions, with only enumerated source/identity changes;
- complete current/legacy recipes, nested-generation refusal, exact scalar
  distinctions, prehash metadata bounds, fixed relative owners and source gates
  before caller hooks, plus refusal to relabel legacy producer updates;
- unchanged hard-three/cadence-two and BOS64 boundaries, malformed public
  checkpoints refusing before Torch, and detached discovery;
- small CPU authored constructors: all13 context tensors, a target-free prefix
  forward with cloned weight snapshots, the seeded gated projection, and full
  13/15-tensor exports from real fresh Adam with no optimizer update. An untouched
  Adam must refuse a falsely claimed completed update.

The tests use lightweight namespace containers to skip broad package-root
initializers while importing the genuine selected owners. Proposal bodies are
read-only, source-pinned AST oracles; they are not executed as artifact runtimes.
The CPU controls allocate authored model topologies and fresh Adam states but
perform no backward pass or Adam step. They are engineering fixtures, not new
training or a model-quality benchmark.

The canonical source-migration cohort qualified 64 experimental controls, including the CPU constructors, two target-free context forwards and two genuine fresh Adam zero-step exports. The [single qualification receipt](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-source-migration-20261019-01/qualification-summary.json) also binds parent-native/catalog/official regressions, current source identities, durable output inventory and original resource closeout. The initial full run's optional-dependency presence-probe fault and failed disposition remain separate history; the corrected full run passed 88 unique cases without a product or test change.

Ten additional [complete-recipe controls](../../../../../workspace/test-logs/federal-corpus-audits/parent-native-genuine-20261020-01/qualification-summary.json) call genuine current context, gated-state and journal metadata owners. They check complete registered historical/current generations, nested mixed-generation refusal, exact shared/public source descriptors and the original gated migration-list contract. Numerical/provider imports are denied; ordinary reads permit declared source/proposal bytes and exactly two SHA/size-authenticated CID codec tables, with explicit arbitrary-resource and sibling-code rejection. No dependency or recipe producer is replaced, and absent optional packages are not forced present. This ordinary-import fixture is not complete package-initialization or raw-import provenance attestation.

These ten controls and ten existing-owner process-lifecycle controls passed together in corrected cohort03. Original run01 remains failed at18 passes/two CID-dependency metadata guard failures, with compute/source closed and64MiB storage retained. The same combined record separately covers two actual fictional parent Lean builds; that native result is not model/checkpoint equivalence or convergence evidence. No original model/checkpoint/data replay, numerical forward, optimizer update or training campaign ran in these new source-only controls.

[The retained gated-state replay attempt was blocked before pytest](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/attachment-ledger-failure-analysis.json). Earlier attempt02 executed neither optional case: zero checkpoint restores, Adam allocations, GRU forwards, backward passes or updates. A native grant was allocated, but child attachment failed on the disk-ledger lock before the productive startup barrier opened. The base owner had recorded an in-memory child identity before the failure; its descendant tracker was not yet retained, so cleanup could not establish its normal tracked-scope closure. The [exact later inspection](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/current-custody-inspection-02.json) reports the native grant absent; historical native release remains unknown. The [owning source controller closeout](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/partial-attachment-source-closeout-observation-02.json) records its observed exit and reap, closing that source READ without a normal context-release receipt. The [original storage cleanup attempt](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/storage-closeout-attempt-02.json) was refused on its inspection lock before reconciliation; its 64 MiB promise was initially retained. A [later explicit reconciliation](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/storage-closeout-attempt-03.json) released that selected storage claim through its original owner and preserved all original failure artifacts. Historical native release remains unknown. This earlier attempt02 supplies no checkpoint parity or model-quality qualification, and no training should be repeated to address that infrastructure failure.

The existing focused test file contains two optional retained-state cases, selected only by an owned request with the frozen asset-manifest and private-export enrollment. Earlier attempt02 executed neither case: it never reached pytest or its four planned restores and two teacher-forced saved-prefix forwards. That earlier attempt has zero numerical work. Later04 reached both cases and failed during each first Adam setup, as recorded below; neither attempt establishes checkpoint parity. The prepared success-only documentation installer remains unused.

[Five resource-owner cases passed](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/owner-qualification-summary-03.json) after the installed partial child-attachment correction: the genuine blocked-child failure, two rejected-identity controls and two existing attachment/tracked-scope regressions. Original source, compute and storage closed. These five cases qualify ownership and cleanup; they supply no checkpoint or model-quality result.

[Replay04 reached both selected cases and both failed](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/independent-failed-replay-review-04.json) during the first restore/Adam construction, before named optimizer moments or any GRU forward could be checked. The test replaced distinct public Torch functions with one sentinel; lazy Adam initialization then imported genuine torch._dynamo and rejected duplicate object rules. The pinned source and both traces imply two restore entries and two Adam/base-Optimizer constructor entries, with zero completed restores/Adam constructors, GRU forwards, backward passes, updates or generation. These are partial path-derived observations; no per-arm success counters or saved-logit reports were produced. The source READ, native compute and observed descendant/group scope closed normally. Its selected 64 MiB storage claim was later released through the original owner, preserving all four failure artifacts. See the [actual storage cleanup receipt](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/failed-replay-storage-closeout-04.json). All six original assets are unchanged. The owning test's genuine Dynamo preflight was installed after this failure. The separately recorded replay05 qualifies its bounded original-state and saved-prefix behavior only; failed04 supplies no equivalence or model-quality result.

[Two retained gated-state cases passed](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-retained-gated-replay-20261020-01/qualification-summary-05.json) in fresh replay05 through the canonical adapters: four complete model/named-Adam restores and two teacher-forced saved-prefix forwards. All 49,404 logit coordinates matched the original pre-update references exactly. Each arm restores step1 and final step2; its one 46-token forward uses step1 weights and the saved pre-update step2 prefix/reference. Final step2 is restored without a forward. Caller model/Adam/JSON and CPU RNG controls passed; cursor/progress checks are metadata only. The genuine Dynamo preflight ran before test instrumentation. This is a target-exposed authored oracle, not target-free inference or statutory accuracy. No backward pass, optimizer update, autonomous generation or new training occurred. Next-update continuation, Context150 and journal replay remain unqualified.

Exact context150 checkpoint reload, target-free retained candidate/termination parity, historical auxiliary/Adam continuation, complete journal checkpoint/resume replay and original inference traces remain **unperformed** for the canonical port. The selected historical artifacts contain no raw-logit oracle; aggregate parity summaries cannot qualify a new retained-logit comparison. Historical qualifications and adverse model-quality results keep their original versions and scopes. These controls establish no statutory correctness, convergence, qualified human review, Lean admission, commit or publication.

The first preflight request stopped before resource admission after a concurrent change to a pinned source; no tests ran and its source lease closed. Retry02 collected 31 cases: 7 passed and 24 failed at the import fence because relocated bytecode lookup was outside its allowed roots. The full cohort remains failed and unqualified. Its isolated-profile export omitted reservation and compute-lease identities, so storage and native-compute dispositions remain null. Conservatively account for the full 128 MiB storage promise until an original reservation ID or owner terminal receipt permits typed inspection; source READ release establishes no compute/storage release. The successful retry does not close that failed attempt.

Retry03 passed the same 31 metadata checks with the existing tracked-descendant profile and fresh private source-tree bytecode lookup. Its installation then refused before source WRITE or replacement because concurrent owning-test additions changed the canonical preimage. Retry04 preserved those additions and passed 31 checks, but two 300-second source-WRITE waits and a later zero-second admission attempt all refused before acquiring WRITE or replacing canonical files. A fourth installation acquired and released WRITE but refused a changed non-document runtime source before any replacement. Its original pending/resume records remain historical snapshots. Retry06 already qualified the five earlier runtime/test changes. Retry07 was required by the subsequent concurrent owning-test merge; it also captures the current parent native guide without treating documentation changes as a reason to repeat tests. Retry07 qualifies the same selected metadata controls against its updated frozen source snapshot. These four documentation files were subsequently rebased onto their current preimages, preserving newer parent-shared preparation and gated-replay progress; their new bytes were not tested. Retry05 preparation was cancelled before source READ custody, native admission or tests; it adds no executed cohort. These repeated controls are not independent additional examples, and the selected 31 cases do not newly qualify the concurrently added gated-checkpoint tests. The [pre-merge evidence](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-context-preflight-20261020-01/pre-merge-qualification/qualification.json) and its installation refusal remain separately retained, alongside the [uninstalled retry04 qualification](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-context-preflight-20261020-01/prior-qualified-uninstalled/qualification.json) and its four installation refusals.

Retry06 separately passed 31 checks and 93 phases, with original source/native/storage releases, but two installation attempts timed out before WRITE or replacement. Its qualification, both refusals, pending record and original documentation remain archived. Retry07 preserves the concurrent 262-byte Dynamo initialization fix in an unselected gated test and qualifies the merged owning-test file with the same 31 metadata checks. Those checks do not execute that gated fix or supply numerical replay qualification. The updated parent native guide is captured in the new immutable manifest; no extra documentation exception applies beyond the four existing write targets.
