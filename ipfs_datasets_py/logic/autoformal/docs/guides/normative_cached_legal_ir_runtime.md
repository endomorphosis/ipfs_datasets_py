# Reuse retained native source caches with selected normative decoders

`normative_cached_legal_ir_runtime` adds an explicit source-cache contract for the
selected `normative-wording-zero` and `normative-wording-ce` LegalIR states at
384D and 768D. It reuses the original weights, raw donor, preprocessing and
native paragraph/clause embeddings. It executes no encoder or training step.
The [original cached runtime](normative_legal_ir_runtime.md) continues to require
its saved original validation split.

```python
from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub
from ipfs_datasets_py.logic.formalization.autoencoder import normative_cached_legal_ir_runtime as runtime

request = {
    "ir_family_id": "legal_ir",
    "dimension": 768,
    "dimension_role": "input_embedding",
    "task_id": "semantic_IR_reconstruction",
    "checkpoint_sha256": checkpoint_pin["sha256"],
    "decoder_contract_id": runtime.DECODER_CONTRACT_ID,
    "training_recipe_name": "normative-wording-ce",
}
plan = checkpoint_hub.prepare_normative_cached_legal_ir_runtime(
    request,
    checkpoint_pin=checkpoint_pin,
    preprocessing_pin=preprocessing_pin,
    donor_checkpoint_pin=donor_checkpoint_pin,
    source_cache_pin=source_cache_pin,
    source_plan_pin=source_plan_pin,
    production_pin=production_pin,
    source_owner_pins=source_owner_pins,
    row_ids=row_ids,
)
```

Each pin supplies a canonical absolute path, exact byte count and SHA256. Current
source pins must cover the 27 fixed paths returned by `source_owner_paths()`.
Preparation stays in the standard library. The corresponding
`open_normative_cached_legal_ir_autoencoder` accepts the same arguments and
restores the existing numerical owner. The caller configures one CPU thread;
`infer_cached()` generates candidates at batch eight and output cap 512.

## Source contract and retained records

The execution contract is `normative-retained-source-cache-legal-ir/v1`. Its
closed seven-field request preserves family, dimension/role, task, exact state
and selected recipe identity. The input cache must be
`fresh-scalar-source-inputs-single/v1`, joined to
`fresh-scalar-source-plan/v1` and `fresh-scalar-source-production/v1`.

The bounded source plan has exactly 48 paragraphs, 180 unique clauses and 216
unique native vectors. It retains the twelve paragraphs in each 1/2/4/8-clause
group, source aliases and order. Preparation independently reassembles the whole
source packet through the existing native validators and compares typed
canonical JSON against the supplied cache. It checks paragraph, clause and
context vector joins, literal UTF8 character/byte offsets, complete untruncated
token records and width-specific representation identities. Original producer
and clause-context digest conventions are preserved, including Unicode.

Native 384D records retain the pinned GTE-small revision. Native 768D records
retain the original multilingual model/code revisions and CLS/L2 profile.
The latter separately declares a historical 8192-token profile and actual
512-token experiment limit. Recorded forward observations, complete loading,
dense-path check, execution profile and seven published asset identities must
agree. Those checks read metadata and archived source witnesses, without
loading or checking encoder asset payloads again. Full transitive dependency
closure and executed-encoder attestation remain unqualified.

The existing selected role, exact zero/auxiliary weight, 32-value codec, tensor,
donor, frozen initializer, TRAIN transformation, normalization and count-prior
checks remain in force. External source geometry has its own gate; the adapter
does not invent an original preprocessing source binding. Saved input transforms
are applied once by the unchanged numerical model before clause padding; saved
paragraph and clause normalizations remain separate model stages.

## File custody and numerical boundaries

Checkpoints, donor, preprocessing, caches, reports and current Python owners must
remain single-link regular files. Archived producer source and the declared
384D source artifact have a separate historical witness policy: canonical
regular files with observed link counts between one and 128. Exact descriptor
identity, byte count and SHA256 are checked repeatedly; archived code is never
imported or executed. Original archived locators are retained.

This accommodates the two producer source files with 26 links in the retained
384D cohort. It also preserves the 384D source artifact's first-attempt locator,
which differs from the r2 cache directory. Changes to either current or
historical generations refuse before loading or after candidate generation, as
observed. Joint closing identity checks follow both read fences. They are
endpoint checks, not an atomic cross-file snapshot or continuous source lease.
A refusal after numerical return retains the detached candidate and truthful
load/inference flags.

## Measurement and supervisor scope

Actual replay uses the earlier exposed-v3 modality wording cache and four
selected states. A separate process compares generated token/status/EOS outputs
to the retained same-state predictions after generation is durable. This
measures implementation parity on existing inputs. It is neither a new semantic
holdout nor legal-text reconstruction or new training progress.

The native ModelManager selector stays exact and separate from the execution
contract. Preparation derives it without opening a manager or database; binding
resolution remains false until a caller makes its own read-only observation.
Native IR schema/profile/format selectors remain null. Runtime release, quality,
teacher, source semantics, long-span and proof qualification remain false.

TRAIN augmentation, prospective DEV60, other IR families, 8D features, different
codecs/prose tasks and arbitrary newly encoded source inputs are not admitted
through this contract. They need their own schema/task-specific adapters and
source records. A repository proof index additionally needs current revision,
span/dependency bindings and the relevant formal/proof validators before the
symbolic planner can treat candidates as evidence.

## Recorded validation on October 7

The 105 new boundary controls and 240 existing runtime/numerical/output controls
pass without failures or skips. An independent source review approved the final
27-owner closure and the actual retained-record refusal checks. Bounded CPU1
replay generated four selected states × 48 paragraphs, with EOS on every row,
unchanged tensors/vectors and preserved RNG. Subsequent separate-process
comparison found 48/48 exact token/status/EOS agreement with each same-state
archived exposed-v3 prediction file. These are replay results, not new gold or
legal-prose scores. Source/result evidence is retained in the workspace's
`artifacts/normative-retained-cache-runtime-20261007` contribution.

## Retained baseline selection and next statutory profile

The 2026-10-21 selection retains `normative-wording-ce` at 384D and 768D as
research candidates, with the matching zero-auxiliary states as controls.
This is a selection for compatible reuse, not model promotion. The
[selection inventory](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-planning-review-20261020-01/review-06/retained-baseline-selection.json)
preserves original options, metadata plans, asset descriptors and exposure.
The later [raw asset custody check](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-planning-review-20261020-01/review-06/retained-baseline-asset-custody.json)
freshly matched all twelve deduplicated state/preprocessing/donor/cache/plan/
production files (40,551,818 bytes) to their recorded hashes under original
source READ. These sequential file checks are not an atomic snapshot or producer execution attestation. It did not deserialize a state, restore tensors, open a model,
generate outputs, create Adam or execute a training update.

State paths below are relative to
`workspace/test-logs/decoder-normative-wording-r2-20261006/` in this repository.
All states retain `private-native-dimension-source-state/v1`; each selected/last
pair is one tensor endpoint, not independent training replications.

| Width / recipe | State | Raw file SHA256 |
| --- | --- | --- |
| 384D / `normative-wording-zero` | `training-384-r1/results/normative-wording-zero/selected-state.json` | `82f326a83a2d00cc1628ff2e9baf3096aa887348bd07e49883ed3e7c0234014e` |
| 384D / `normative-wording-ce` | `training-384-r1/results/normative-wording-ce/selected-state.json` | `6cab6fe31ef7c98db1508001bc64926b7ff176ef2a9bd385473d8e05f5f8c266` |
| 768D / `normative-wording-zero` | `training-768-r1/results/normative-wording-zero/selected-state.json` | `c8beca3ef5ea2d477ebc9a1564c8922404b245098a0b56083197cd6185c3083f` |
| 768D / `normative-wording-ce` | `training-768-r1/results/normative-wording-ce/selected-state.json` | `aa2f75cad0ade34a3965a4f0b71bdc2fe962f5b863b38133927978ea2673aeb3` |

Use the existing `checkpoint_hub` prepare/open entry points above. Keep the
historical original48 and retained fresh48 input profiles separate. Historical
replay of four states on48 paragraphs is already complete; it is not a new
holdout. The lexical output contract remains `typed-json-lexical/v1`, with32
tokens, five actor names, five actions, two objects, O/P/F and syntax tokens.
Its output vocabulary cannot express arbitrary statutory atoms or qualifier
strings. Nonempty qualifier coverage remains unqualified; lexical availability
of a quoted token does not establish its suitability for a particular field.
This fixed48 runtime excludes new inputs; the separate
[arbitrary-source runtime](arbitrary_native_legal_input_cache.md) already supports
new source-bound 384D/768D caches without widening the output vocabulary.
The retained decoder accepts up to eight clause vectors, saved preprocessing,
one CPU thread, batch8 and output cap512; encoder and decoder limits have
different units. `optimizer_resumable=false` requires a declared new optimizer
generation for new fitting. Source width is not bottleneck width.

Twenty-six of27 current owner bodies still match their historical pins.
`ir_model_manager_import.py` is the sole changed owner in this observation;
review its compatibility and freeze current owners before any new replay.
Historical worktree locators remain historical, including absent paths. The
current runtime was not requalified. In particular, recorded native-vector
binding checks do not change the retained plan's
`saved_paragraph_vector_producer_authenticated=false` or
`complete_runtime_io_contract=false` declarations.

## Pilot representability checklist

This checklist separates existing new-source input support from remaining
complete-target/head decisions. It grants no permission to widen the fixed48
cache gates or count input support as output representability.

| Complete input or target | Existing coverage | Required disposition |
| --- | --- | --- |
| Retained normative regression row | Existing fixed cache and32-token vocabulary | Reuse its original replay contract and exposure labels. |
| New statutory text | Separate [arbitrary-native input/runtime contract](arbitrary_native_legal_input_cache.md) already implemented for 384D/768D | Reuse its exact source/cache/producer checks; preserve the fixed48 runtime boundary. |
| Unseen lexical symbols | Outside the saved normative32 output vocabulary | Preserve output incompatibility; never substitute names or strip qualifiers. |
| Nonempty qualifiers | Training/evaluation used empty qualifiers; quoted-token presence does not establish field coverage or legal meaning | Assess lexical, structural and reviewed-meaning requirements separately; retain every qualifier. |
| One anchored flat rule | [Canonical byte codec](../../../legal_ir/canonical_byte_codec.py),259 IDs, exactly one rule and complete nonoverlapping leaf anchors | Use only if the supplied target already satisfies its fixed operators and sorted/unique qualifier contract. Do not sort or deduplicate a different target to force acceptance. |
| Ordered predicate roles, bound variables and Boolean/quantified/modal structure | Existing [relational target contract](legal_relational_decoder_target_contract_v1.md) and [compact codec](legal_relational_compact_codec_v1.md) | Reuse their versioned target owners; a compatible model head/checkpoint is still required. |
| Retained section7213 alternatives | Existing exact relational/compact replay and19 unresolved obligations per hypothesis | Preserve both interpretations of the same physical use; they are not two uses. |
| Complete section7214 norm | No accepted complete norm AST or governing applicability decision | Retain source-only/null label. Counting/equality requirements need an explicit supported grammar and reviewed target. |
| Governing definition and two uses | Existing scoped lookup, applicability and definition/use review | Require two distinct occurrences and independently supplied governing-meaning/every-use decisions. |
| Source edition/legal-as-of | Existing source/review contracts | Keep missing values explicit; repository/signature times or formal Nat time cannot fill them. |
| Full graph and Lean component | Existing proposal, definition/use, shared/native/incremental owners | Preserve their exact supported fragments and unresolved full-norm integration. |

The relational profile already covers bound Object variables, ordered roles,
binary and/or/implies/iff, negation, forall/exists and explicit O/P/F. Its current
profile still rejects equality/distinctness, constants/functions, counting,
additional sorts, shadowing, n-ary connectives, temporal operators, purpose and
anaphora. It requires null source binding and authored-unreviewed declarations.
Broader underlying AST support does not widen this profile automatically.

Reuse the saved section7213 measurements: each complete alternative encodes to
7,256 canonical byte IDs or2,452 compact IDs including BOS/EOS. Neither fits a
512- or1,024-ID budget in those codecs. That transport measurement is already
complete; it supplies no trained head. A shared259-ID alphabet does not align
the flat, relational or compact sequences or their learned output layers.

Reuse `arbitrary_native_source_cache` and `arbitrary_native_legal_ir_runtime`
for the already implemented new-source path, or the existing retained pointer
runtime for its limited grammar. Complete source/edition/coordinate and review
references, independently available context, width-specific producer custody,
untruncated token/chunk policy, saved preprocessing and grouped split/exposure
remain profile-specific requirements. Bind a complete target codec and output
budget; expected labels stay outside inference inputs. Preserve ambiguous or
unreviewed targets. The original eight-source pilot is evidence, not a run to
repeat as new integration work.

An expanded or different output grammar requires a new checkpoint generation or
an explicitly qualified architecture/token-head migration. Record which tensors
are reused versus initialized and declare optimizer policy; replacing the32-token
head with259 tokens is not an exact checkpoint continuation. Qualify refusals,
complete round-trip, autonomous BOS output and source-dependence under existing
execution owners before interpreting a new training result. Do not fit a partial
target and report reconstruction of the complete norm.

## Next implementation delta

The existing `logic/formalization/autoencoder/ir_cell_target_compatibility.py`
now exposes `inspect_normative_legal_ir_targets`, also delegated by
`checkpoint_hub`. It adds pure fixed-codec inspection for declared normative
384D/768D requests; `preflight_ir_cell_cached_targets` retains its original
source-pinned 384D cell contracts. No source cache or runtime was replaced.
The [qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-normative-target-compatibility-20261021-01/qualification-summary-v01.json)
passed 190 cases / 570 phases: 131 existing owner cases and 59 new cases. The
first collection attempt ran zero cases because its frozen source list omitted
the genuine IPFS router availability probe. The retry added that source only;
all product/test bytes and case selections remained unchanged. Original source,
native and storage custody closed for both attempts; failed logs remain retained.

### In-memory fixed-codec inspection

Pass exact UTF8 JSON bytes and an independently expected raw SHA256. The closed
request contains `schema`, `decoder_request` and `rows`:

```python
request = {
    "schema": "normative-legal-ir-target-inspection-request/v1",
    "decoder_request": selected_normative_request,
    "rows": [
        {"id": occurrence_id, "source_sha256": declared_source_sha256,
         "canonical_ir": independently_supplied_target_or_none},
    ],
}
report = checkpoint_hub.inspect_normative_legal_ir_targets(
    request_raw, expected_request_sha256=expected_request_sha256,
)
```

`selected_normative_request` is the existing closed seven-field declaration:
family `legal_ir`, exact integer 384/768, role `input_embedding`, task
`semantic_IR_reconstruction`, declared checkpoint SHA256, one of the three
existing normative decoder contract IDs and recipe `normative-wording-zero`
or `normative-wording-ce`. The inspector opens no files, runtime, model or
network. The outer raw hash pins supplied request bytes; source/checkpoint
hashes remain unverified declarations. Saved transforms, source occurrence,
producer execution, exposure grouping and review are not authenticated here.
Source text, vectors and expected targets never enter an inference call.

The report reuses the original lexical encoder and exact 32-token codec hash.
Whole quoted statutory atoms remain whole tokens: no character/subword fallback
or vocabulary fitting occurs. Complete token counts include BOS/EOS and the
fixed 512-ID budget; overflow is reported without truncation. Numeric, Boolean
and null tokens inside a nonnull target are retained as OOV evidence rather
than silently skipped. Duplicate JSON keys, nonfinite numbers, invalid UTF8,
changed raw pins, extra request/row fields and duplicate IDs refuse. Bounds are
2 MiB per request, 64 rows, 512 KiB per nonnull label, depth 64 and 100,000 nodes.

Every selected row remains in order. `pending` means a null label; `unsupported`
means outside the declared one-to-eight-rule/seven-facet shape; `incompatible`
means a supported shape with OOV or overflow; `covered` means the inspected
shape and lexical encoding fit. Lexical coverage, complete length and shape
support are separate fields even for unsupported targets. Distinct IDs sharing
a source hash remain distinct declarations, not proof of distinct physical uses.
Known words swapped between roles, and nonempty or unsorted/duplicate qualifier
strings, can be lexically covered. Qualifier order is preserved. Field-role
meaning and inherited native grammar remain unverified; eight source/scalar
slots do not assert that native syntax ends at eight rules. All labels remain
unreviewed and all training, quality, producer, runtime and proof authority flags
remain false. No checkpoint loading, inference or training ran in this cohort.

### Runtime-bound fixed-codec inspection

`preflight_normative_legal_ir_targets` in the same compatibility owner, also
exposed by `checkpoint_hub`, binds the unchanged inspection request to existing
source-only runtime preparation. Pass the exact pinned inspection bytes plus a
closed `runtime_options` JSON object and its independently expected canonical
SHA256. Canonical options bytes use sorted keys, compact separators,
`ensure_ascii=False`, `allow_nan=False` and UTF8. The wrapper bounds options to
2 MiB, depth 64 and 100,000 nodes before detaching them.

```python
report = checkpoint_hub.preflight_normative_legal_ir_targets(
    request_raw,
    expected_request_sha256=expected_request_sha256,
    runtime_options=source_only_options,
    expected_runtime_options_sha256=expected_options_sha256,
)
```

Reuse the selected existing preparation owner's options, with its `request`
argument removed. All profiles require `checkpoint_pin`, `preprocessing_pin`,
`donor_checkpoint_pin`, `source_owner_pins` and ordered `row_ids`. The original
saved-source profile additionally takes `source_inputs_pin` and
`source_contexts_pin`; the retained-cache profile takes `source_cache_pin`,
`source_plan_pin` and `production_pin`; the arbitrary-source profile takes
`source_cache_pin`, `source_requests_pin`, `native384_receipt_refs`,
`native768_report_refs` and `source_artifact_pins`. Only `deadline_seconds` and
`max_reference_bytes` are optional. Labels, `request` and extra fields refuse.
The corresponding decoder contract IDs are
`normative-selected-cached-legal-ir/v1`,
`normative-retained-source-cache-legal-ir/v1` and
`arbitrary-native-source-cache-legal-ir/v1`, respectively.

The wrapper calls the genuine selected public preparer twice, bracketing pure
inspection, and requires identical complete plans. It binds ordered occurrence
IDs, exact source-text hashes, selected checkpoint, saved preprocessing, owner
receipts and the fixed32 codec/512-ID output budget. It returns a detached
metadata report without source text, vectors or source-input packets. All target
rows and diagnostic counts survive unchanged, including null, OOV, overflow and
unsupported rows. Targets never enter preparation or model inputs. Mutation of
preparation arguments or the returned opening plan refuses.

Source custody remains profile-specific: original and retained source-cache
rows do not acquire the arbitrary profile's physical-span contract. The arbitrary
profile preserves explicit artifact/request/offset occurrence bindings, including
distinct occurrences with identical prose. Retained historical evidence receipts
and link policy keep their existing consistency scope. Source/native record
consistency does not attest encoder execution. Repeated endpoint and per-file
fences are not an atomic multi-file snapshot.

The [binding qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-normative-target-binding-20261021-01/qualification-summary-v01.json)
records 229 cases / 687 passed phases, comprising the existing
190 controls and 39 added cases. Fixtures exercise all three genuine
public preparation routes. Arbitrary cache planning/validation and physical
source reads are genuine; native384 record admission alone uses declared
fixture records. Retained-cache historical native admission also uses its
existing fixture double. The qualification receipt preserves both failed attempts, the dependency-manifest
fix and the exact receipt-only privacy-assertion correction. No encoder attestation, retained-asset numerical result,
model restore/forward, optimizer update or legal review follows from these tests.

### Compact role source/BOS preflight

The existing `ir_cell_target_compatibility` owner and its thin `checkpoint_hub`
delegate add a separate pure metadata operation:

```python
report = checkpoint_hub.preflight_compact_role_bos_sources(
    request_raw, checkpoint,
    expected_request_sha256=request_sha256,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_policy_sha256=policy_sha256,
    source_resolver=source_resolver,
)
```

The closed request uses `schema="compact-role-bos-source-preflight-request/v1"`,
required plain-integer `max_new_tokens` in 1..511 and one to 16 ordered `rows`.
Each row has exactly `id`, `source_request`,
`expected_source_request_sha256`, `input_id`, `receipt_ref`, `context_raw_utf8`,
`expected_context_sha256`, `context_origin`, `target_content_raw_utf8` and
`expected_target_content_sha256`. A receipt reference contains only absolute
`path`, positive `bytes` and exact raw `sha256`. A pending target uses null for
both target fields. Requests are bounded at 8 MiB, unique referenced receipts
at 64 MiB in aggregate, and complete reports at 16 MiB; overflow refuses.

The operation repeats intact role inspection and the existing public native384
source conditioner at opening and closing, preserving ordered occurrence/input
identities, full source-input/span declarations, exact receipt/binding hashes and
availability status. Equal prose at different physical selectors remains distinct.
`missing_input` and `token_limit_exceeded` rows remain unavailable. Reports retain
source text metadata and vector hashes, with no conditioning vector or executable
packet. Source reports, options, input snapshots and owner pins have mutation and
closing checks; these are per-file/repeated endpoint fences, not atomic custody
or function-bytecode attestation.

The genuine 537-entry token/context and completion-budget owners inspect fixed
prefix `[1]` with origin `bos_seed` for the
[explicit BOS-v2 consumer](legal_compact_content_completion_budget_v1.md#explicit-bos-generation-v2).
The output contract remains 512 total IDs including BOS/EOS. For an encoded
target, `new_ids = total_ids - 1` includes EOS: a 101-ID target fits allowance100
and exceeds allowance99. This is capacity inspection, not a completion guarantee.
Null targets stay pending; unsupported counted shapes, token overflow and other
actual token-encoding refusals retain `not_encoded`, an error class/message and
unknown counts. Raw target, canonical target and encoded-ID hashes remain
separate. Labels are passed only to target inspection, never to the existing role
inspector, source conditioner or prefix policy. The intact role inspector still
validates its historical training targets.

`context_origin` declares `authored_fixture`, `target_derived_label` or
`caller_supplied_unverified`; the exact raw context has its own hash. A declaration
does not establish independent inference availability. Native GTE384 receipt
transport also does not qualify the retained CP128 authored sparse conditioning
space. The report therefore always has `generation_ready=false`,
`execution_packet=null`, zero training/evaluation masks and false authority,
including conditioning compatibility and context permission. It performs no
generation, model restore/forward, encoder replay, training, review or Lean action.

The [source/BOS qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-role-bos-source-preflight-20261022-01/qualification-summary-v01.json)
records 254 cases / 762 passed phases: 229 retained owning controls and 25 added
controls, across 87 selectors, 206 frozen files and 229 outer source pins.
Authored inspector/conditioner/checkpoint doubles remain distinct from genuine
source-factory/snapshot and token/context/budget controls; no actual checkpoint
inspection or native-conditioning integration ran in this cohort. The two earlier
real native-conditioning preparations retain their separate evidence. Successful02
closed its original source/native/storage custody. Failed01 ran zero cases and
refused before any native/storage owner existed; its saved trace and administrative
source-controller closeout remain preserved, with null original native terminal
and unknown historical child birth. The historical 229-case/687-phase binding
result above remains unchanged.

The separate [retained-checkpoint/native384 observation](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-retained-role-bos-preflight-20261022-01/qualification-summary-v02.json) now joins the intact authored CP128 checkpoint with the two existing native384 rows through the genuine public preflight. One direct data operation made two role inspections and four source preparations; both rows are embedded and both targets remain pending. The 284/242-byte sources retain complete 51/47-token receipt identities and one shared 11,415-byte receipt. The same exact 1,128-byte authored fixture context is declared for both rows, with no asserted source correspondence or independent inference permission. BOS allowance 100 remains metadata only. Native GTE384 compatibility with CP128 authored sparse conditioning is unqualified. Original native/storage/source custody closed; model restores, numerical forwards, encoder replay, generation and training were zero. Readiness stays false, the execution packet null and masks/authority zero/false. The original owned execution took 298.113 seconds against its unchanged 300-second cap; this timing includes observational controls and is not a throughput or inference-speed result. Inspect that cost before batch expansion. The earlier 254-case engineering cohort and completed native captures were reused without rerunning them. The first saved-metadata audit refused an extra namespace-initializer assumption; the corrected metadata-only successor preserves that failed receipt and the unchanged successful operation.

### Source/head conditioning contracts

`ir_cell_target_compatibility.inspect_source_head_conditioning_v1` compares two
independently pinned UTF8 JSON declarations without reading files, importing a
model or applying a transform:

```python
report = compatibility.inspect_source_head_conditioning_v1(
    source_contract_raw, head_contract_raw,
    expected_source_contract_sha256=source_raw_sha256,
    expected_head_contract_sha256=head_raw_sha256,
)
```

Both documents use the closed `legal-conditioning-space-contract/v1` schema
with exactly nine fields: `schema`, `artifact_sha256`, `boundary`, `dimension`,
`producer`, `preprocessing`, `ordered_transforms`, `basis` and
`required_side_inputs`. The artifact hash is an independently supplied origin
declaration; this operation does not open or authenticate that artifact.
Dimensions are plain integers 8, 384, 768 or 4096. Boundaries are `encoder_output`
or `decoder_input`; the head must describe `decoder_input`.

`producer`, `preprocessing` and `basis` contain complete recipe objects with a
nonempty string `schema`, or null when unavailable. `ordered_transforms` is an
ordered list of such objects, or null; an empty list explicitly declares no
transform. `required_side_inputs` is a list of complete recipe objects, retained
without satisfying its requirements. Documents are bounded at 4 MiB, depth32 and
50,000 JSON nodes, with at most64 list entries for transforms or side inputs.
Duplicate keys, nonfinite numbers and unsupported primitive types refuse.

The `legal-source-head-conditioning-inspection/v1` report preserves raw document,
artifact and complete component hashes. An encoder output yields
`adapter_required` before comparing it with the decoder boundary, retaining all
component differences and unknowns. At the same boundary, known differences in
dimension, producer, preprocessing, ordered transforms or basis yield
`refused_contract_mismatch`; otherwise missing components yield
`conditioning_contract_unresolved`. Complete exact declarations yield only
`declared_contract_match`. Component comparisons preserve JSON value types and
transform order; a matching width or caller-assigned space name cannot replace
missing recipes. A declared mismatch is not a theorem of mathematical
incompatibility, and this inspector does not rule out an existing adapter.

Describe the actual boundary after the existing runtime's transformations;
retain fitted centering/scaling, clause vectors, masks and raw-text requirements
separately. The saved 384D/768D wording heads require transformed source context;
CP128 sparse conditioning, spaCy8 features and the learned8 formula donor retain
different bases. The 4096D span decoder's source-text input remains explicit.
The inspector supplies no adapter, complete-model input validation, learned
compatibility, context permission, training, model quality or convergence credit.
`full_decoder_input_verified` and `execution_ready` stay false, all authority
flags stay false and training/evaluation masks remain integer zero.

The [focused qualification](../../../../../docs/autoformalization/evidence/legal-ir-source-head-conditioning-20261025.json)
passed **30 authored metadata cases / 90 phases** from 21 selectors. Its frozen
namespace captured 36 source files, recorded 35 source-compilation observations and observed 33 import
origins; the backend router was an availability-only capture. Original source,
native/resource and storage custody closed. These cases qualify declaration
comparison and refusal behavior, with zero model, encoder, training, SQL or Lean
execution. Retained checkpoints/native receipts, complete public-package startup,
actual learned conditioning compatibility and permitted context remain outside
this cohort. Historical metadata inspection supplies no new API replay or
retained-data qualification.

#### Original checkpoint and TRAIN provenance

`ir_cell_target_compatibility.inspect_normative_checkpoint_conditioning_v1`
derives the existing head-contract format from independently pinned original
checkpoint, preprocessing and donor JSON bytes, with an optional original TRAIN
input bundle:

```python
bound = compatibility.inspect_normative_checkpoint_conditioning_v1(
    checkpoint_raw, preprocessing_raw, donor_raw, training_inputs_raw,
    expected_checkpoint_sha256=checkpoint_raw_sha256,
    expected_preprocessing_sha256=preprocessing_raw_sha256,
    expected_donor_sha256=donor_raw_sha256,
    expected_training_inputs_sha256=training_inputs_raw_sha256,
    training_recipe_name="normative-wording-ce",
)
```

The additive API retains the original 384D/768D zero/CE recipes and fixed
normative32 codec. It reuses the existing contextual JSON, document and source-row
validators; it opens no files or model and applies no vector transformation.
Each raw artifact is bounded at 32 MiB, with a 64 MiB aggregate bound. Entire
supplied metadata is parsed, including historical count-prior information;
source-only row validation does not establish target independence or permission.

Raw whole-file hashes and the original training identity remain separate.
The closed `matched-dimension-source-inputs/v1` bundle retains its own canonical
`inputs_sha256` seal. The canonical sorted, compact, ensure_ascii=False UTF8 hash
of `dimensions[str(width)]` must equal both the checkpoint lineage's
`input_provenance_sha256` and preprocessing's `source_inputs_sha256`. This is not
the raw bundle-file hash, and a current inference cache cannot replace the
original training population. Ordered TRAIN/validation IDs, recorded
representation, context binding and clause-training context hashes must match
the saved preprocessing. Opaque historical training-cohort digests remain
separate from source-only row hashes.

The derived `head_contract` keeps paragraph and clause recipes distinct:
saved input centering/scaling then paragraph-feature normalization, and the
separate clause chain of input centering/scaling, padding to eight slots and
clause-feature normalization with its source-derived Boolean mask. These are
retained recipes, not executed adapters or transformed inputs. Missing original
TRAIN bytes leave producer/basis unresolved. The retained 384D representation's
null profile also stays unresolved when its training bundle is supplied; the
768D profile supplies recorded metadata only. Its historical 8,192-token profile
and 512-token experiment admission remain separate and are not relabeled.

The report schema is `legal-normative-checkpoint-conditioning-inspection/v1`.
It retains raw hashes, the original semantic lineage digest, optional training
counts/representation, a detached head contract and unresolved fields. All
authority flags remain false, execution/full-input readiness false, and
training/evaluation masks integer zero. It supplies no current inference-source
compatibility, encoder execution, training, held-out accuracy, legal meaning,
Lean admission or model-convergence qualification.

The [qualification record](../../../../../docs/autoformalization/evidence/legal-ir-normative-checkpoint-conditioning-20261026.json)
keeps the authored **21 cases / 63 phases** from 13 selectors separate from the
retained-artifact cohort's **four cases / 12 phases** from one selector. Each
cohort used the same 46-file frozen generation and separately recorded 35
source-compilation observations and 33 import origins. Source, native/resource
and storage custody closed for both runs; neither ran a model, encoder, new
training, SQL or Lean operation.

The four retained reports bind eight original artifacts / 36,148,366 bytes.
Both recipes at each width reuse one original 48-TRAIN / 48-validation exposed
benchmark population. Their semantic lineage hashes remain separate from the
raw bundle-file hash; no new independent legal examples or learning scores are
created. The 384D profile remains unprovided and the 768D profile is recorded
metadata only. An empty metadata `unresolved` list grants no current
inference-source compatibility, producer execution, context permission,
accuracy or convergence. The earlier declaration inspector's 30 authored cases /
90 phases retain their original independent scope and were not repeated.

#### Original 384D saved-metadata lineage

The [saved-metadata audit](../../../../../docs/autoformalization/evidence/legal-ir-original384-metadata-lineage-20261026.json)
traces the original exposed authored-benchmark TRAIN lane through its source
plan to **96 CPU paragraph
vectors and 167 unique CUDA clause vectors**. The clauses occupy **360 ordered
context slots**. All literal text, split/ID, vector and slot joins match the
retained inputs. These 263 role-specific views contain 239 unique literal texts;
24 texts occur in both roles and all 24 pairs have different float32 bits
(largest component difference `1.1920928955078125e-07`). Keep paragraph and clause
roles when indexing; source-text deduplication alone would change saved inputs.

Both original paths record the same nine model-asset identities. The CPU
producer uses the historical runtime; the CUDA clause runner uses
`SentenceTransformer.encode(normalize_embeddings=True)` after its model's
Normalize module. The current runtime source hash differs from the historical
CPU runtime, and the CUDA records retain pretokenization hashes rather than full
forward-token receipts. Asset metadata agreement does not authenticate either
execution, establish a common numerical profile or supply missing receipts.
Model-weight files were not rehashed and no encoder was replayed in this audit.
The CPU numerical functions have matching ASTs across the inspected runtimes;
the source differences concern asset-file inspection. This narrows the code
delta without establishing environment parity or numerical equivalence.

The original custom CPU/CUDA records do not satisfy the current native receipt
schema and runtime checks. Preserve them unchanged. The existing binder's
384D `profile_id`, producer and basis remain null/unresolved; do not recast old
records as current native receipts or replace original TRAIN lineage with the
later inference cache. This metadata-only audit adds no API, pytest/native
qualification, compatible head, model quality or convergence result.
The audit parsed source/reference documents and serialized decoder-state
metadata; it supplies no target-independence claim.

##### Indexed receipt overlap and prepared successor inputs

The [finite overlap audit](../../../../../docs/autoformalization/evidence/legal-ir-original384-receipt-overlap-20261026.json)
checks exactly two indexed receipt populations: eight statutory spans and two
heading candidates. None of their ten inputs matches an original paragraph,
unique clause or clause slot by exact UTF8 text or float32 bits. All 96 paragraph
views, 167 unique clause views and 360 slots remain uncovered by these two
populations. This is not an inventory of every cached receipt. Each receipt's
recorded configuration remains separate; no native validator or encoder ran.

The same record points to a prepared diagnostic successor request packet using
the existing source-cache and producer wire contracts. Two derived UTF8 carriers
retain the 48 TRAIN and 48 validation paragraph occurrences. Each split has 48
cache requests and 216 distinct complete producer input identities, within the
unchanged limits of 64 requests and 256 inputs. The 456 paragraph/clause role uses
map to 432 inputs, preserving 24 whole-paragraph/single-clause aliases, all 263
historical vector views and all 360 slot mappings. Deduplicating the 239 literal
texts would lose the physical selectors needed by the cache.

The immutable packet retains its historical `unvalidated_prepared_request`
status. Its source kind is `diagnostic`; newly materialized carrier custody
does not restore original legal or producer provenance. It contains no new
vectors, tokens or receipts. The separate typed/source qualification below
closes its input-geometry prerequisite without rewriting the packet. The later
native capture below records current tokens and two actual producer receipts for
these exact inputs. The later canonical cache observation accepts these 96 diagnostic
requests; head/conditioning comparison and broader consumer gates remain separate.
Preserve both original role vectors
when comparing a shared successor input. Original/successor conditioning IDs
remain unresolved; preparation grants no semantic, learning, Lean or convergence authority.

##### Genuine typed/source validation of prepared inputs

The separate [six-case qualification](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-input-validation-20261026.json)
passed **six cases / 18 phase events**: two actual prepared-data operations and
four genuine refusal controls. Existing `SourceSpan.from_dict`,
`EmbeddingInput.from_dict`, `validate_embedding_inputs` and source-cache
`_requests` accepted 432 typed inputs and 96 paragraph requests, preserving all
456 role uses, 360 clause slots and 24 whole-paragraph/single-clause aliases.
The positive operations made four source-resolver calls; the refusal controls
made three separately counted calls. The refusals reached altered-text source
binding, duplicate physical selector, wrong-carrier artifact identity (size/hash,
not exclusively a hash failure), and valid-but-shifted cache-span gates.

Actual returned objects and eight pinned DATA bodies / 2,869,212 bytes were held
through final serialization and session teardown. The ordinary frozen-source
profile captured 13 files, recorded 11 import origins and 12 source-path compile
observations; these are not exact compiler-buffer or cryptographic execution
attestation. The backend router observation was availability only. Original
source READ, actual native resource grant and storage custody closed, with zero
live owned processes. The terminal's semantic `admitted=false` does not negate
that separately recorded resource grant.

These text/source contracts are dimension-independent even though the packet was
prepared for a 384D producer. The immutable packet retains its historical
`unvalidated_prepared_request` status; this separately selected qualification
closes its typed/source geometry check without rewriting it. That six-case
operation exercised no tokenizer, encoder, model, new vector/token/receipt, full
native cache or head compatibility. Conditioning IDs remain unresolved, readiness
false and training/gold masks zero. The separate native execution profile is
recorded below.
The subsequent native capture and canonical cache observations close tokens,
receipts and selected 96-request cache consumption. Reuse those closed results
before separate original/successor input and head comparison. Original
legal/producer provenance, meaning, permitted context, learning, Lean and
convergence qualification remain open; the original 16 MiB TRAIN bundle was not
opened or requalified by this operation.

##### Actual native384 capture of the prepared diagnostic inputs

The separate [closed native capture](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-native-capture-20261027.json) reused the six-case input qualification
without replay. Two genuine public producer calls returned two receipts with all
432 exact ordered inputs embedded and no token-limit or missing-input refusals.
The 96 paragraph and 360 clause roles retain all 456 uses; 24 complete-payload
aliases share successor inputs. Every role keeps its original physical/source
binding and old vector references through the selected receipt index.

Both receipts record a concrete CPU float32 profile: batch16, mean pooling/L2,
inference mode, one CPU thread, seed0 and no truncation. Actual Torch is
`2.9.1+cpu`; both splits span9–72 tokens. The producer checked nine pinned assets
and actual forward token evidence; genuine receipt save/reload, held objects,
closing file identities and original source/native/storage cleanup passed.
This is bounded native receipt evidence, not runtime cryptographic attestation.
Original/successor **conditioning** profile IDs remain unresolved; the native
execution profile above is recorded. Preserve the old mixed CPU/CUDA vectors and
decoder checkpoint. The subsequent canonical cache observation closes selected
request consumption. Original/successor input/head comparison and reviewed
statutory source/meaning/context remain separate. No decoder, training,
SQL or Lean operation ran; training/gold masks and semantic authority stay zero/false.

##### Canonical source-cache acceptance and exact-byte copy

The separate [canonical cache qualification](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-source-cache-20261027.json) passed two actual data cases /
six phases using the existing planner and saved-byte validator in the canonical
repository. Both 48-request splits are complete: 96 ready diagnostic benchmark
paragraphs, zero refusals, 360 clause slots, 456 role uses and 24 complete-payload
aliases to 432 native inputs. All 912 stored vector copies match their selected
receipt float32 bits. These are authored benchmark paragraphs, not statutory
provisions or reviewed legal targets.

The observed calls were four planner entries (two direct plus two internal
validator rebuilds), two validators and eight ordinary receipt-loader returns.
No encoder, producer, decoder, optimizer, training, SQL or Lean operation ran.
The unchanged ordinary worker enrolled 21 sources and 42 source/control pins;
it recorded 16 module names, 15 physical origins and 15 compile-path observations,
without compiler-buffer or whole-runtime attestation. Nine producer-file paths
remain canonical; no frozen-path rewrite or second cache campaign was needed.

A separate original-owned operation copied 12 files / 9,420,264 bytes exactly
into the workspace, retaining the original temporary outputs and both sets of
descriptors. This durable copy adds no new cache validation result or external
publication. Original source/native/storage custody closed for both operations.
The first attempt failed setup before any cache API because the existing
repository bootstrap lacked a source pin. Its six files remain retained; the
original storage owner reconciled that reservation separately. Only the successful
two-case attempt receives qualification credit.

The separate commitment-only review found 0/456 equal original/successor float32
BE commitments. It measured no distance, cosine, tolerance or learned-head effect.
Original vectors/checkpoint and unresolved conditioning IDs remain unchanged.
Reuse these exact caches and closed qualifications without re-encoding or
replaying their campaigns; normal consumer source, receipt and current-generation
checks remain required. Metadata/declaration inspectors do not perform numerical
parity. Correct input/conditioning/head comparison, reviewed source/meaning/context,
training/gold, Lean and convergence retain their separate admission gates.

##### Actual raw source-vector drift, before head qualification

The [separate raw-drift qualification](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-raw-vector-drift-20261027.json) reuses the accepted caches and native
receipts. The existing `contextual_legal_ir_numeric.compare_source_vector_drift_v1`
now owns the pure comparison. Twenty authored binary32 math cases / 60 phases
qualified that additive API separately from one actual data case / three phases.
The actual operation called it once on all 456 ordered physical role uses,
retaining 263 historical views, 360 clause slots, 432 successor identities and
24 complete-payload aliases. It never collapsed uses by text or selected a first
nomination. Original and successor values were already exact float32; no repair,
quantization, preprocessing, encoder, decoder, model or training operation ran.

No row is bit-exact: 164,730 of 175,104 coordinate pairs differ. Maximum absolute
error is 1.4901161193847656e-7; maximum L2 is 6.010568178496229e-7; maximum stable
cosine distance is 1.780813733906834e-13; maximum signed-rank float32 ULP distance
is 492,527. All per-row distances, norms, relative L2, dot/cosine and ULP reports
are retained. These measured limits supply no acceptance tolerance, causal
runtime explanation, common-basis qualification or head/equivalence guarantee.
The earlier commitment-only observation remains a distinct historical result.

The admitted child parsed the whole original JSON, including target-bearing
metadata. Only closed `{id, original, successor}` source-vector rows entered the
math API; its `target_access=false` is kernel scope and does not claim the outer
reader left target bytes unopened. Original mixed CPU/CUDA vectors, checkpoint
and unresolved conditioning IDs remain unchanged. The prior native receipt's
concrete CPU float32 / batch16 / mean+L2 profile remains recorded.

The 19-source, 43-pin ordinary operation observed eight import origins and eight
compile paths, without compiler-buffer or whole-runtime attestation. Original
source/native/storage custody closed. A separate original-owned exact copy kept
the original outputs and durable metadata copies; it added no numerical result
or external publication. Accepted caches' nine producer-file hashes are unchanged.
The additive numerical source changes the contextual facade's whole-file pin,
so future facade preparations must refresh that generation instead of rewriting
historical plans. Reuse all closed campaigns; normal consumer source, receipt
and current-generation checks still apply. The separately closed retained-head
point observation below adds no conditioning/basis, reviewed statutory meaning/
context, training/gold, Lean or convergence qualification.

##### Saved preprocessing and fixed BOS retained-head sensitivity

Reuse the [closed retained-head observation](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-head-sensitivity-20261027.json). The existing numerical owner's
`compare_contextual_source_sensitivity_v1` has a separate 21-case / 63-phase
authored Torch qualification. One admitted actual operation authenticated and
restored the retained ordered-clause CE head once, then made two paired probe
calls, preserving the original 48 TRAIN / 48 validation boundaries. This is the
30-float32-tensor / two-int64-buffer contextual head, separate from F18's 42-state
branch. All 456 physical roles, 263 historical views, 432 native identities and
24 aliases survive. The 360 real clause slots supply metric observations;
408 padded cells are audited separately, without invented padding observations.

Eleven stage families cover saved paragraph/clause transforms, projection,
feature normalization, all real-clause scalar/recurrent start states, hidden and
count logits, and raw/float32-centered BOS logits. None has a bit-exact paired
row. Maximum absolute BOS-logit difference is 2.384185791015625e-6; the largest
scalar-head difference is 1.811981201171875e-5. The separately calculated stable
binary64 centered-delta maximum is 2.0922161638736725e-6. All 96 BOS argmaxes
agree, but **both arms always select token 30 of 32**, with no ties. Original
top1/top2 margins span 5.777725458145142–8.540583968162537; successor margins span
5.777722954750061–8.540585160255432. These are descriptive observations with no
acceptance tolerance, diverse-prediction, task-accuracy or equivalence claim.
After BOS the genuine grammar routes paragraph plus the first real clause0;
later clause decoder steps and full sequences remain untested even though all
real-clause start-state features were measured.

The diagnostic now validates each physical occurrence with the genuine per-row
context validator, preserving row IDs, slots, hashes and offsets. Four repeated
successor-text groups contain eight occurrences with distinct embedding JSON
hashes; original inputs have no such group. No causal runtime explanation is
asserted. This probe-local receipt does not change or admit packets into the
legacy global text-to-one-vector validator, full inference or training contracts.
The separately qualified numerical consumer below retains this occurrence
boundary. Reuse the separately qualified facade metadata path below;
explicitly admitted retained generation still precedes trajectory comparisons.

The actual forward used CPU float32, one thread, highest matmul precision and no
CPU autocast, with frozen weights and unchanged ambient CPU RNG. The refreshed
13-source generation and seven metadata owners yielded 20 module origins and
20 compile-buffer observations; this is no native-binary or whole-runtime
attestation. Accepted caches' nine producer hashes are unchanged. The admitted
reader parsed whole original JSON including target fields, and the retained
count prior includes historical TRAIN-label fitting; source-only probe packets
do not establish outer target independence. No source encoder, normalization or
count-prior fitting, optimizer, free generation, SQL or Lean ran in this actual
operation. Original source/native/storage custody closed normally.

All attempts remain distinct: the first fixture import stopped before tests;
the second exposed the incorrect BOS-sentinel expectation and cache-write audit;
the third child passed 20/60 but its owner failed administratively and required
original storage recovery. The corrected fourth cohort passed 21/63 normally.
The first actual attempt returned a binder and one restore, then refused the
global context invariant before a numerical report; its original recovery is
retained. The successful retry adds one restore and two probes, not a replay or
replacement of those histories. Reuse these closed results with normal current
source/receipt checks. Reviewed statutory source/meaning/context, conditioning
basis, complete outputs, training/gold, graph/Lean and convergence remain open.

##### Versioned numerical occurrence inference

The [separate numeric-consumer qualification](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-occurrence-inference-20261027.json) adds
`contextual_legal_ir_numeric.infer_contextual_legal_model_occurrences_v1`.
It accepts distinct paragraph IDs with repeated text and retains every ordered
clause occurrence, including same-text clauses with distinct authenticated vectors.
Genuine per-row validation and the existing batch builder feed one shared greedy
computation; legacy inference keeps its validation/results and training/BOS
contracts remain unchanged. This does not silently route existing facades here.

Twelve new 384D authored cases / 36 phases passed, including genuine legacy/new
EOS-output parity, mixed one/eight-slot masks at batch16, repeated paragraph/clause
identities, source bindings and callback/model/RNG/tensor mutation refusals.
Synthetic model setup uses authored normalization/count-prior fit receipts and
fixture targets. Explicit status-taxonomy doubles cover consumer bookkeeping;
they supply no neural trajectory evidence. The prior 21-case BOS cohort and
retained-data/native/cache/raw campaigns were reused without replay. CPU float32,
one thread, highest matmul precision and no CPU autocast remain explicit.

The new schema separates `execution_completed` from `eos_completed`; a deadline
before the first batch reports zero greedy calls rather than invented inference.
Raw EOS, output-limit, invalid-special and deadline dispositions are retained.
`decoded_IR_valid` and `task_satisfied` remain null/unassessed: neither EOS nor
fixture parity establishes valid IR or task success. Actual call-start/return
counts are per invocation, not inferred from the twelve test cases.

Reuse the separately qualified versioned facade below and its genuine 48-row
metadata preparation and the two-row retained-generation observation below.
Further retained controls/comparisons require fresh admission and a declared policy.
Retain historical plans and refresh current source-generation pins; neither
fixture qualification nor metadata preparation supplies numerical compatibility,
complete typed IR/graph/Lean or source/meaning/gold/convergence authority.

##### Versioned occurrence artifact facade

The [facade-v2 evidence](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-occurrence-facade-v2-20261028.json) adds
`prepare_arbitrary_native_legal_ir_runtime_v2` and
`open_arbitrary_native_legal_ir_autoencoder_v2` in the existing arbitrary-native
runtime owner. They require `arbitrary-native-source-cache-legal-ir/v2`; v1
prepare/open and their fixed contract still use the legacy numerical path.
Both versions share original source/native/cache validation and custody. V2
adds the existing cache owner's exact-float32 preflight and numerical UTF8
bounds before a model can open, then dispatches only to the separately qualified
`infer_contextual_legal_model_occurrences_v1`. No new cache or model registry is
created, and the nine cache producers and numerical/training owners stay fixed.

Twelve new cases / 36 phases qualify facade metadata and dispatch with explicit
native/cache and numerical doubles. They cover repeated paragraph/clause uses,
v1/v2 and hidden-policy refusals, source/native/current-owner fences, selected
entry/code stability, and detached diagnostics after a post-return refusal.
These inert controls add no neural or genuine native-join evidence.

A separate admitted operation genuinely prepared the accepted 48-row authored
TRAIN cache (180 ordered clauses) through v2. Its one prepare-v2 entry and zero
open-v2/numerical-owner entries authenticate the selected source artifacts,
saved native records, cache and current source generation within the original
endpoint fences. It is metadata preparation, not 48 reviewed statutes, a model
restore or generation run. No encoder, fitting, SQL or Lean follows. Historical
count-prior/TRAIN exposure, unresolved source meaning and zero masks remain.

V2 separates numerical API call start/return from actual model start/execution.
A returned zero-greedy deadline reports model flags false; a started call with
an unobserved/malformed result reports unknown, not an evaluated failure. The
new numerical report still keeps execution completion, EOS and unassessed IR/task
validity distinct. Raw diagnostics survive post-return custody refusals even
when reported model execution was false. None of these flags grants authority.

Reuse the separately closed two-row retained-generation observation below.
Reuse the original/successor trajectories and paragraph/clause input-block
contrasts below. Select a substantively different bounded diagnostic only after
declaring its independent policy, with a freshly checked v2 plan. Keep all closed native/cache/raw/BOS/
numerical and facade fixture campaigns separate; no repeat is needed.
Keep normal source/receipt/current-generation checks and the unresolved reviewed
source/edition/meaning/context, held-out targets, model basis, graph/Lean release
and convergence gates. The 768D retained numerical branch stays unqualified.

##### Retained facade/direct generation observation

The [bounded retained-generation record](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-retained-generation-pair-20261028.json) uses two already-exposed authored
TRAIN paragraphs: first minimum/maximum literal clause counts (1 and 8; original
indices 0 and 36). Selection used no model output or target/reference score. One
public v2 open and one retained CE-head restoration were followed by one facade
inference and one direct occurrence-API call on the **same observed source packet
object and same restored handle**. Raw return objects, detached facade output,
source/metadata and model/callable state were held through terminal checks.

Facade: EOS 2/2, contract-valid 2/2, complete candidates 2/2; direct: EOS 2/2, contract-valid 2/2, complete candidates 2/2.
Disposition `exact_raw_report_parity`; complete raw report serialization equality `true`, prediction equality `true`, inspection equality `true`.
Canonicalization changed 1/2 facade and 1/2 direct generated payloads; the ordered model output stays separately preserved.

Each arm used output cap 512, deadline 120 seconds and batch 8 with CPU float32,
one intra/inter-op thread, highest matmul precision and no CPU autocast. Actual
call/start/step counts and raw status/token lengths remain in the saved reports.
If either arm meets a deadline, the comparison is incomplete/inconclusive even
when empty outputs happen to match; no automatic retry or equality credit follows.
The observation is this finite wiring check, not general source-to-model or
semantic equivalence, robustness, convergence or an independent test panel.

Generated content was inspected twice by the existing
`contextual_legal_ir_output.inspect_contextual_legal_predictions`, reusing
`decoder_source_fidelity` and `CanonicalRoundTripIR@1`. No new parser, F18 metric,
reference scorer or source-text renderer was used. Contract validation and EOS
are post-generation observations; `complete_candidate` does not prove that all
source clauses or legal requirements are represented. Canonicalization may sort
rules/qualifiers or deduplicate qualifiers, so its view must not replace ordered
raw output. The raw reports' IR/task fields remain null; legal meaning, complete
task satisfaction, reviewed gold and semantic fidelity are unassessed.

No encoding, cache rebuild, fit/optimizer, SQL or Lean occurred. Whole retained
checkpoint/preprocessing metadata and historical TRAIN-label count-prior exposure
remain explicit; source-only inference does not establish outer target independence.
Original source/native/storage custody closed under the saved worker/owner
dispositions. All earlier cache/raw/BOS/numerical/facade campaigns remain separate.
The separately admitted original/successor trajectory observation below now
records one bounded source-pair comparison. Reviewed source/edition/meaning/
context, supported held-out targets, model basis, graph/Lean release and
convergence remain open.

##### Original/successor source trajectories

The [bounded source-trajectory record](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-source-trajectory-20261028.json) reuses the same two already-exposed
authored TRAIN paragraphs, original indices 0 and 36 with 1 and 8 literal clauses.
The existing full16-asset adapter joins historical and successor physical source
roles before selecting these rows. One public v2 open/restoration authenticates
the successor metadata, then the existing occurrence API runs original and
successor source packets on the same restored handle. Facade inference runs zero
times. Two generated-only inspections reuse the existing output/fidelity and
`CanonicalRoundTripIR@1` owners. No product API or decoder was added.

Original: EOS 2/2, contract-valid 2/2, complete candidates 2/2; successor: EOS 2/2, contract-valid 2/2, complete candidates 2/2.
Disposition `matched_prefix_source_trajectory_observed`; 309 paired active equal-prefix points, including 231 physical later-clause points (`observed` later-route coverage). Raw prediction equality `true`; raw report equality `false` is not an acceptance criterion.
Maximum raw absolute logit delta `1.33514404296875e-05`; maximum stable centered delta `1.4379620552062988e-05`; no acceptance tolerance. Canonicalization changed 1/2 original and 1/2 successor payloads; ordered output remains separately preserved.
Row 0 (1 clauses): no differing actual choice at the observed matched points; paired physical later slots []. Row 36 (8 clauses): no differing actual choice at the observed matched points; paired physical later slots [1, 2, 3, 4, 5, 6, 7].

The run-specific observer uses genuine bound `next_logits` and caller `_greedy`
frames, with no method patch or replayed scanner. It retains full 32-logit
vectors, actual input/state/route/return tensors and clones through terminal
checks. Genuine chosen IDs come from the following actual input or final greedy
return, including EOS/invalid IDs omitted from content lists. Matched comparisons
require both rows active with exactly equal complete consumed prefixes and
matching position/grammar/routes/sites, through the first differing choice.
Later autonomous traces are descriptive. Inactive post-EOS points are excluded;
physical later routes 1..7 require the genuine source mask true in both arms.
Padding and sentinel routes, scalar sites and count boundaries remain separate.

Each arm retains cap512/deadline120/batch8, CPU float32, one intra/inter-op thread,
highest matmul precision and no CPU autocast. Existing raw-f32 and stable centered
diagnostics separate bit identity, numeric differences and preference changes;
an additive shift is not a preference change. No tolerance or equivalence credit
is inferred. Deadline observations stay incomplete/inconclusive with no retry;
unreached matched physical routes stay unobserved. Joint source packet and hidden
history differences do not isolate a causal effect of any single clause.

Raw IR/task fields stay null. EOS, contract conformance and a complete candidate
do not establish source coverage or legal fidelity; canonicalization keeps its
separate changed-payload flag. Whole original JSON and both-split metadata were
read, with historical TRAIN checkpoint/preprocessing/count-prior exposure. This
is no held-out or reviewed statutory panel. Masks remain zero, conditioning IDs
unresolved, and graph/Lean, source-to-model semantics, task satisfaction and
convergence remain open. Original source/native/storage custody closed; no
encoder, fit/optimizer, cache rebuild, SQL, Lean, reference scorer or earlier
campaign was replayed. The separately admitted input-block contrasts below
reuse these historical endpoints without another generation; retain each scope.

##### Saved-only paragraph/clause input-block contrasts

The [saved-only factor record](../../../../../docs/autoformalization/evidence/legal-ir-prepared384-conditioning-factors-20261028.json) retains two synthetic experimental packets
over the same exposed authored TRAIN rows (indices 0/36; 1/8 literal clauses):
`paragraph_only` combines successor paragraph rows with original clause contexts;
`clauses_only` combines original paragraph rows with successor clause contexts.
The existing full16-asset adapter authenticates all endpoint physical roles.
Hybrids retain whole endpoint row/context objects and exact IDs, text, offsets,
vector bits and masks. They are experimental input combinations, without an
invented whole-cache/native receipt or native-cache admission.

The original observer exited 1 after both generations/inspections and endpoint
reuse, at a tuple-versus-JSON-list equality assertion in the four-edge comparison.
Its failed source and outputs remain unchanged. A separate metadata-only
reconciliation compares the saved JSON traces using existing pure raw/centered
metrics; it imports no Torch, restores no model and reruns no generation. The
original operation stays incomplete. Its last attained live guard was comparison
entry; no final live terminal receipt, final import/compile/audit snapshot or
terminal object/model/RNG custody is claimed. Original native/source cleanup and
separate original-owner storage recovery are recorded independently.

One successor-metadata public v2 open/restoration preceded the two direct
occurrence calls, then two existing generated-only contract inspections. Facade
inference and fresh original/successor endpoint generation are zero. Historical
O/S traces are opened only after both current calls and inspections, then joined
to their accepted result/summary and exact artifacts, product sources, runtime
entry/policy, reconstructed packet hashes, model digest and codec hash. Transform
continuity is provenance-derived from unchanged preprocessing/restoration sources;
no prior Python object or unrecorded transform-content identity is claimed.
Historical and current handles/processes remain distinct. A mismatch refuses
reuse, with no fallback endpoint generation. Native runtime binaries are not
fully attested by these source/entry checks.

Paragraph-only: EOS 2/2, contract-valid 2/2, complete candidates 2/2; clauses-only: EOS 2/2, contract-valid 2/2, complete candidates 2/2. Canonicalization changed 1/2 and 1/2 payloads, respectively.

| Edge | Paired active prefixes | Physical later points | Max raw logit delta | Max stable centered delta | Predictions equal | First actual-choice divergence |
| --- | ---: | --- | --- | --- | --- | --- |
| `original_to_paragraph_only` | 309 | 231 (observed) | `2.384185791015625e-06` | `2.2724270820617676e-06` | `true` | row 0: none at observed matched points; row 36: none at observed matched points |
| `original_to_clauses_only` | 309 | 231 (observed) | `1.33514404296875e-05` | `1.424551010131836e-05` | `true` | row 0: none at observed matched points; row 36: none at observed matched points |
| `paragraph_only_to_successor` | 309 | 231 (observed) | `1.33514404296875e-05` | `1.4439225196838379e-05` | `true` | row 0: none at observed matched points; row 36: none at observed matched points |
| `clauses_only_to_successor` | 309 | 231 (observed) | `2.384185791015625e-06` | `2.141110599040985e-06` | `true` | row 0: none at observed matched points; row 36: none at observed matched points |

Disposition `four_edge_conditioning_factor_observation`. Each edge keeps its own both-active exact full-prefix cohort
and first-choice divergence cutoff; counts are not pooled across edges. The
saved traces preserve actual chosen terminal IDs, grammar/routes/sites and
32 logits. Original live input/return tensor guards attained comparison entry,
not a final terminal closure. Physical later coverage
requires actual mask-enabled routes 1..7 in both arms; padding, sentinels and
inactive post-EOS points supply no later-clause credit. After divergence,
autonomous traces stay descriptive. No minimum point count, nonzero delta,
prediction agreement or acceptance tolerance is required. Raw bit identity,
numeric change and stable centered preference change remain separate. Deadlines
stay incomplete/inconclusive and unreached routes stay unobserved, with no retry.

These factors are input vector blocks, not isolated decoder pathways: paragraph
vectors affect persistent conditioning, hidden history and count guidance;
clause vectors affect scalar heads and recurrent residuals. Route/site coverage
does not isolate a head or slot. Cross-run edges grant no within-run causal,
isolated-clause, additivity, interaction or generalization claim.

Cap512/deadline120/batch8 and CPU float32/highest/no-autocast/one intra/inter-op
thread stay fixed. Raw IR/task fields remain null; EOS and generated contract
completion do not establish source coverage or legal fidelity. Canonicalized
views retain changed-payload flags and never replace ordered output. Whole
original JSON/both-split metadata and historical TRAIN checkpoint/preprocessing/
count-prior exposure remain explicit. Masks stay zero and conditioning IDs
unresolved. No product API, encoder, cache rebuild, fit/optimizer, SQL, Lean,
reference scorer or old campaign was replayed. Source/native/storage custody
closed through separate owner receipts; this does not complete the failed live
worker. Reuse these saved-only conditional observations; choose a substantively different
bounded diagnostic only after declaring its independent policy. Reviewed source
targets and source/definition-grouped held-out evaluation, legal fidelity,
graph/Lean release, semantic source-to-model equivalence and convergence remain open.

An earlier original-owner recovery recorded an inventory-entry-bound refusal
under the historical `0a2` resource profile. That failed profile's numeric
inventory threshold is unattested here. The immutable renewed preflight's
`failed_recovery_inventory_bound=2,500,000` field was an inference, and is not
adopted as the failure threshold. Separately, the newer `d6b8` peer preimage
already declared 2,500,000 entries. The qualified two-literal repair changes that
current peer limit to 4,000,000 and updates the stale production-cap test
assertion. Three existing cases/nine phases cover the production constant
without admission and the inclusive limit/overflow refusal in strict and non-strict modes. The exact
two-file candidate, qualification, per-file CAS installation/readback and renewed
storage profile are linked in `operational_headroom`; current peer source/test
bytes outside those two literals were preserved. The 220 GB cap, 16 MiB ledger
bound, accounting, roots and guards stay fixed. The actual original-owned storage
release has its own receipt. This finite repair supplies no whole-operations
qualification, failed-worker success or missing final live custody.

Continue within LIR-17/19 using the existing receipt, conditioning and training
owners:

1. Reuse the completed two-population overlap audit without rerunning it.
   Additional indexed receipts, if separately nominated, must retain exact text,
   float32 bits, every input nomination, producer/config, paragraph/clause role,
   split and physical source identity; never select the first text hit.
2. Only uncovered required views need a proposed bounded successor capture.
   Commit its assets, runtime/config, complete forward tokens and raw vector
   bits, while retaining all 96 paragraph identities, 167 unique clauses and 360
   slot occurrences. Shared text may reuse a qualified successor vector only
   under that successor's explicitly declared role policy.
3. Reuse the closed raw/BOS reports, occurrence consumer, v2 facade and
   48-row metadata preparation, plus the separately observed two-row retained
   facade/direct pair, original/successor trajectories and conditional
   paragraph/clause input-block contrasts. Select a substantively different
   bounded diagnostic and independent policy under current source/native/artifact
   checks; retain historical/current process distinctions and separate cohorts.
   Keep raw completion, EOS and post-generation contract observations separate
   from source coverage, legal task fidelity and convergence. Legacy v1/training
   contracts remain fixed; historical reconstruction needs its own profiles.
4. If conditioning differs, qualify an explicit adapter or a separately named
   checkpoint lineage before using the head. Fit any adapter on TRAIN only;
   retain source/definition-grouped validation and independent checkpoint
   selection. Reviewed complete source/context/AST targets and independently
   permitted context still precede statutory fitting. Keep the four-width
   comparison, complete autonomous task scores and convergence claims separate.

The earlier declaration and raw checkpoint/TRAIN qualification cohorts were not
rerun. Source edition, meanings, governing definitions, inference permission,
training/gold eligibility, graph/Lean admission and convergence remain open.

### Remaining review and complete-output work

Reuse the existing target, numerical and review owners through the compatibility
contract below. Runtime binding retains its existing scope; a new profile needs
its own complete-target and source/context decisions.

### Complete-target handoff and counted-profile port contract

The next change is a declared compatibility handoff between existing owners.
The [runtime-bound diagnostic](#runtime-bound-fixed-codec-inspection) has passed
229 engineering cases / 687 phases. It authenticates selected runtime/source
bytes within its stated fences, while labels remain unreviewed evaluator input.
The [counted correspondence](legal_source_typed_norm_join_v1.md#explicit-counted-frame-correspondence-v2)
has separately passed 158 authored cases: 98 existing controls and 60 counted
controls. Neither result supplies reviewed statutory labels or complete norms.
No additional codec, model, training run or public API is added by this handoff.

#### Reuse the existing token families and their separate profiles

| Token family | Existing target contract | Preserve its boundary |
| --- | --- | --- |
| Normative 32 | Fixed lexical JSON and the selected 384D/768D normative checkpoints | Complete lexical OOV/length and declaration-shape inspection; arbitrary terms, bound variables and counted structure do not become flat atoms. |
| Anchored flat 259 | [Canonical byte codec](../../../legal_ir/canonical_byte_codec.py) | Exactly one seven-facet rule with complete nonoverlapping leaf anchors and sorted/unique qualifier lists; do not rewrite a different target to force acceptance. |
| Relational 259 | [Canonical byte target](legal_relational_decoder_target_contract_v1.md) and [compact byte transport](legal_relational_compact_codec_v1.md) | Both retain the complete supported relational request. Their payloads, sequence lengths and learned output coordinates are different despite the shared byte alphabet. |
| Compact content 537 | [Existing content head](legal_compact_content_head_v1.md), fixed content tokens and separately supplied signature/role context | Predict identity-free structural content; original identity sidecars remain archival/evaluator material. This is an existing numerical profile, not a proposed new expanded head. |

The relational byte owner already exposes `build_relational_target_codec_v1`,
`encode_relational_target_v1`, `validate_relational_target_encoding_v1` and
`decode_relational_candidate_v1`, with their existing codec/encoding hashes.
The compact byte owner provides the corresponding compact operations. Reuse
these complete-input validators instead of adding another serializer or audit.
The retained section7213 lengths, 7,256 canonical or 2,452 compact IDs including
BOS/EOS per hypothesis, are existing transport measurements. Preserve the two
alternatives as one physical use. The separate [retained537-token intake](legal_compact_content_tokens_v1.md#retained-intake-and-complete-output-budget) already measured both historical alternatives at101 framed IDs each, including BOS/EOS. Reuse that content census; byte-transport lengths and content-token lengths remain distinct.

For content prediction, reuse `prepare_context_v1`, `project_request_v1`,
`decode_prediction_v1` and `reconstruct_request_v1` in the existing
[content owner](../../legal_compact_content_v1.py), plus the fixed
[token owner](../../../formalization/autoencoder/legal_compact_content_tokens_v1.py).
Projection derives context and identity from a supplied reference and is not
evidence of reference-blind inference. Prediction accepts content and context;
exact original-request reconstruction additionally uses the identity sidecar.
Signature order, predicate argument roles, lexical binding and modal placement
must survive the selected operation's actual contract.

The content grammar remains the authored Object/Bool relational profile:
variables, predicates, quantifiers, binary connectives, negation and O/P/F
extensions. It does not support counted v2's EventFrame/TimeFrame sorts or
built-in equality. Byte vocabulary size does not determine constructor support.

#### Existing numerical and budget owners

The 537-token head already has an exact thirteen-tensor state and a transfer
ledger: ten compatible nonlexical tensors copy from its supported native384
parent; `target_embedding.weight`, `output.weight` and `output.bias` map lexical
rows by exact token spelling. Unseen rows use the parent's lexical-row mean.
The ledger records the parent, geometry, weights, initialization and fresh
optimizer requirement; parent Adam is not inherited. Mean initialization is
not learned meaning. Preserve this ledger and the existing checkpoint type.
This transfer path admits its named supported parent; a 384D normative-wording
state is not automatically a supported donor merely because its width matches.

Reuse the [prepared runtime](../../../formalization/autoencoder/legal_compact_content_prepared_runtime_v3.py),
[role-trained serving](legal_compact_content_role_trained_runtime_v1.md),
[prepared role-training lifecycle](../../../formalization/autoencoder/legal_compact_content_role_prepared_training_v2.py)
and opt-in [budget consumer](../../../formalization/autoencoder/legal_compact_content_role_budget_runtime_v1.py).
Source availability is separate from execution qualification: select the exact
consumer version supported by its retained source-pinned receipt, and preserve
any unexecuted parity/adoption proposal as pending. Older proposal/readme
cutoffs do not replace the later trained/prepared and CP128 observations.
Role `inspect`, `score_prefixes`, `score` and `generate` already separate intact
checkpoint validation from a target-free numerical serving view. Validation
still reads the checkpoint's exposed basis targets. Serving omits basis targets
and Adam; that does not make supplied conditioning, prefixes or context blind.

The fixed content codec retains 512 total IDs. Original role generation and
budget `generate` retain their explicit 1..64-new-ID limit. The additive
[BOS generation v2 consumer](legal_compact_content_completion_budget_v1.md#explicit-bos-generation-v2)
fixes `[1]`/`bos_seed` and permits a required plain integer 1..511 allowance,
including EOS, with a separate v2 report schema/profile. Its finite engineering cohort passed 67 cases / 201 phases;
all three failed predecessors remain retained with original custody closed. Both APIs share one original generation
loop and checkpoint/serving owners; the completion lower bound supplies no
completion guarantee. Generic prepared v3 accepts a different checkpoint type;
its larger allowance cannot convert or relabel an intact role checkpoint.

The retained section7213 shapes need 100 new IDs from BOS. The v2 allowance
accommodates that length while preserving v1's 64-ID contract; no new numerical
prediction, checkpoint compatibility, native conditioning-space qualification
or permission for label-derived context follows. Reuse the completed intake.
Retain every refusal and incomplete result; do not truncate or repair EOS.
The original 16 MiB whole-report bound also remains; oversized reports are refused.

The [separate full-declaration diagnostic](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-decoder-profile-20261022-01/qualification-summary-v01.json)
reports all three unreviewed declarations as normative32 shape-unsupported/OOV
and over 512 IDs. That fixed-codec inspection is distinct from the separate
28-entry counted-fragment codec's 293 framed IDs. Increasing the BOS allowance
changes neither target grammar nor those codec contracts, and the 293-ID
fragment does not establish a complete norm or a compatible 537-token checkpoint.

The current role consumer accepts one plain 384-coordinate conditioning vector.
The symbolic signature/role context constrains token selection; it is not an
additional neural source input. Prefix origins include BOS; context origins are
authored fixture, target-derived label or caller-supplied unverified material.
`prepare_context_v1` validates declared signature/roles but does not authenticate
permission, source provenance or exposure. A reference-derived context must
remain explicitly reference-derived. Do not promote it to permitted source-only
context because the eventual numerical call receives no target argument.

The [receipt-bound prepared source route](legal_compact_receipt_bound_prepared_source.md)
already checks native GTE384 source/receipt inputs. Its retained compact
checkpoint was trained on authored sparse vectors: physical source transport
does not qualify the learned conditioning space. Reuse the completed
[CP128 and compact campaigns](../TRAINING_HISTORY.md#compact-role-priority-cp128).
The current prepared role trainer retains two exposed rows, 47 total target IDs
and denominator67. A different corpus, objective or conditioning space needs a
declared compatible training profile and optimizer policy; it cannot reuse an
unchanged-population Adam-resume claim. Do not repeat CP38-to-CP128, weighted128
or scope128 as unfinished work.

#### Commit the source and example correspondence independently

The [existing compact decoder-example companion](legal_compact_decoder_example_v1.md)
already replays the complete original source example and projects its label into
content/context/identity compartments. Its retained275-case qualification is
recorded in the [reconciled history](../TRAINING_HISTORY.md#reconciled-compact-example-and-token-intake).
Reuse it instead of writing another label adapter. Its compact context remains
target-derived label data; it does not close the independent correspondence,
review or permitted-context decisions below.


The [existing example](legal_relational_decoder_target_contract_v1.md#source-labels-and-provenance)
retains `model_input={source_text, context}`, a complete byte-codec label or null,
and separate provenance. Its public `validate_relational_decoder_example_v1`
replays the complete original v1 join and independently pinned request/codec.
Preserve its example, join, target-transport, canonical-encoding and producer
commitments. Hashing a modified report supplies identity, not original custody.

Its physical source key contains original HTML hash/size, source-version CID,
normalized-view coordinate system, character/UTF8 boundaries and span hash.
The arbitrary runtime instead uses SourceSpan artifact hash/size, source kind,
release/document/language/citation, identity-normalized byte offsets and row ID.
An independently supplied correspondence must retain both namespaces and their
exact original inputs. Equal text or `source_group_sha256` cannot establish it.
Reuse the [sampled-source scope](legal_source_norm_scope_v1.md), original view
selector and existing arbitrary-cache validation; do not create another parser.
Normalized-view offsets must never be treated as offsets in original raw HTML.

The example's source/context hash commits the complete two-field input. Runtime
paragraph/literal-clause vectors and compact signature/role context are separate
contracts. Preserve their respective hashes and explicitly state what the
producer consumed. Existing runtime preparation does not establish equality
between those three packets or authenticate a declared embedding reference.
Unavailable mapping, context permission or producer evidence remains unresolved.

Retain independently supplied review/example commitments, source edition/context
and exposure/grouping evidence through the existing review owners. `exposed` or
`unknown` in an example is caller-declared, not a blind split. Preserve shared
source alternatives, unresolved meanings, unassigned splits and zero masks.
This handoff supplies no reviewer decisions, governing definition or admission.
Reuse the existing [typed review responses](legal_norm_content_responses_v1.md):
`build_norm_content_template_v1`, `build_norm_content_response_v1`,
`assess_norm_content_responses_v1` and `validate_norm_content_assessment_v1`.
Both section7213 hypotheses already retain 19 obligations each. The 121 fictional
review/signature controls do not supply submitted statutory answers, trusted
reviewer keys, reviewer independence or an actual review time. Do not create a
replacement packet or manufacture those inputs.
The existing [interpretation-review owner](legal_norm_interpretation_review_v1.md)
replays its complete v1 correspondence, context and dependency evidence before
authenticating signed statements. Its selected-trust prerequisites do not make
`norm_interpretation_ready` true or supply `governing_definition_use`. A counted-v2
review port needs a compatible subject/evidence contract; existing signatures
cannot authorize changed payloads or a new profile by relabeling them.

#### Preconditions for a later counted profile port

The current example and both byte codecs use relational v1. Counted join v2 is
an explicit fixed at-most-three-distinct authored fragment with 49 nodes and six
binders; it is not a complete section7214 norm. The actual retained section7214
source-only/null target must remain pending until an independent target exists.
Serializing a fixed frame and training a constant label would not close that gap.

A future port must replay `validate_counted_frame` and
`validate_source_typed_norm_join_v2` from independently pinned original requests
and complete reports. Preserve the typed expression, all six binders, ordered
Member(object,event,time) arguments, equality endpoints, identity pairs, frame,
maximum, assumptions and every source/introduced unresolved entry. Do not invent
a native AST path for the counted owner's specialized generated-text renderer.

Declare a separate supported profile, complete target representation, codec and
output budget before changing consumers. Reuse existing typed/count owners and
the thirteen-tensor ledger; do not mutate v1 grammars or relabel old checkpoints.
The port's target scope must remain a counted fragment unless independently
reviewed complete-norm construction is separately supplied. It grants no 8D,
768D or4096D compact-head support from the existing 384D implementation.

Acceptance must cover full original-input replay and complete target round-trip,
ordered roles/binders/equality, missing assumptions and unsupported constructors,
changed source/context/codec pins, identical prose at distinct occurrences,
target leakage, and all historical v1/null/alternative behavior. Counted v2 itself
requires nonnull counted inputs; retain v1 for source-only pending examples.
Keep source-byte consistency, producer execution, review, full-norm coverage,
training eligibility and graph/Lean admission as separate recorded outcomes.

#### Declared counted28 head contract

Reuse the existing [declared counted28 head specification](legal_compact_content_head_v1.md#declared-counted28-head-specification)
in `ir_decoder_profile_inventory`. Its public APIs are
`build_counted_content_head_spec_v1(codec, *, expected_codec_sha256, config=None)`,
`counted_content_head_spec_sha256(spec)` and
`validate_counted_content_head_spec_v1(spec, codec, *, expected_spec_sha256,
expected_codec_sha256, config=None)`. They retain the current peer specification
and its original shape owner. No alternative head-spec factory or grammar is
introduced by this handoff.

The spec fixes the expected input to raw native GTE-small384 and reuses the
existing complete counted28 codec with a 512-total-ID limit. Geometry accepts
only hidden size, token embedding dimension and projection width; seeds,
weights, source vectors, corpora and target references are not spec inputs.
The original head's pure shape helper supplies thirteen declared tensors.
Only the three lexical first dimensions change from537 to28. Shape arithmetic
allocates no tensors and supplies no trained checkpoint, prefix API or runtime.

The complementary transfer-only metadata APIs are
`plan_counted_content_head_transfer_v1(spec, codec, *, expected_spec_sha256,
expected_codec_sha256, donor_declaration, config=None)`,
`counted_content_head_transfer_sha256(plan)` and
`validate_counted_content_head_transfer_v1(plan, spec, codec, *,
expected_plan_sha256, expected_spec_sha256, expected_codec_sha256,
donor_declaration, config=None)`. Preparation and validation reuse the complete
public peer spec and original counted codec, with independent retained pins.
This companion declares a possible transfer; it does not reopen or replace
the existing spec, restore weights, initialize parameters or register a route.

The donor is a closed caller declaration: profile, architecture, input width
and role, H/E/P geometry, checkpoint/weights hashes, complete ordered vocabulary
and its digest, declared Torch version and conditioning profile. No donor file
or tensor body is opened. Ten nonlexical tensors would require exact matching
shapes; the three lexical tensors use the original head's token-row helper.
Exact shared spellings request copied rows; new spellings request declared
donor lexical-row means. The selected public compact537/count28 comparison is
23 shared spellings and five new ones, backed separately by the public-codec
observer. These are planned initialization requests, not copied/fitted weights
or learned meanings, and the plan requires a fresh optimizer without donor Adam
continuation.

The target space remains the peer spec's fixed raw native GTE declaration.
The donor keeps its separately declared conditioning profile, and the plan
records a `matching`, `different` or `unknown` declaration relation. None grants
conditioning-space compatibility or training credit. A sparse-trained donor and
native GTE input may have equal widths and incompatible fitted conditioning.
Source-generation, spec/codec, donor-declaration and whole-plan hashes retain
their respective recipes and operation scopes; a hash alone does not validate
original custody or establish source currentness.

The current counted language admits one fixed content tree and one fixed
context. Different expression/signature/node IDs are archival variations,
not a varied target population. The retained293-ID actual fragment remains a
reused mechanical measurement. A constant output can reconstruct that singleton
language without depending on source text, so completion alone cannot establish
autoformalization fidelity. Keep the observer's two authored identity variants
separate from physical-source and independently reviewed statutory counts.

Current counted projection labels its context
`target_derived_authored_declaration`. The lexical source-context owner retains
its existing Object/Bool contract. For counted source/label separation, reuse
the existing [partial counted companion](legal_compact_decoder_example_v1.md#source-only-example-with-a-partial-counted-label-v1):
`prepare_counted_compact_decoder_example_v1` and
`validate_counted_compact_decoder_example_v1`. These v1 companion APIs genuinely
replay the original source-only example and a separately supplied counted v2
join, requiring identical complete scope/source custody and replay inputs.
The original `source_example.label` remains null. Counted context, correspondence
and target IDs remain outside `source_example.model_input`.

Reuse the [249-case peer qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-decoder-example-20261022-01/qualification-summary.json),
including40new companion controls,52head-spec controls and the retained
section7214 observer. Its counted projection and293IDs match exactly; the
exposed, unassigned source-only example keeps `embedding_reference:null` and
zero learning/gold masks. This receipt qualifies its frozen generation, without
repeating that campaign or replacing the separate79-case transfer-plan
qualification. It establishes no correspondence to the separately retained
284/242-byte native heading inputs.

The counted context remains target-derived label information. The companion
does not supply independently permitted source-only counted context, an eligible
training population or a complete reviewed statutory target. A future independent
fixed-context API still needs its own permission and exposure evidence. A fixed
grammar declaration does not derive counting units, statutory roles or meanings
from prose.

#### Counted singleton prefix inspection

The existing target-compatibility owner now has one separate pure API:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import ir_cell_target_compatibility

report = ir_cell_target_compatibility.inspect_counted_content_prefix_v1(
    prefix_ids, context_raw,
    expected_context_sha256=retained_raw_context_sha256,
    codec=counted_codec,
    expected_codec_sha256=retained_counted_codec_sha256,
)
```

It supplies no new module, numerical head, checkpoint, selector, score or
source-conditioning runtime. Its fixed counted28 codec and all old537 owners
remain byte-identical. Existing cached-cell, normative and role/BOS preflight
functions retain their complete original source prefix and separate contracts.
The public Hub has no additional wrapper for this inspector.

The report has schema `legal-counted-content-prefix-inspection/v1` and profile
`authored-counted28-singleton-prefix-inspection/v1`. No target, projection,
identity sidecar, source text, logits, budget override or checkpoint is an
argument. The inspector derives the sole sequence using the counted owner's
public authored request, projection and encoding APIs. The resulting content,
context, ordered28-token vocabulary and293-ID sequence must match the existing
profile commitments. It does not recover a legal interpretation from a prompt.

An empty list is a valid `prefix` with only BOS allowed. Each exact proper
prefix has exactly one allowed next ID. The exact complete293-ID sequence has
status `complete`, no allowed next ID and a `complete_candidate` obtained by
calling the public counted token decoder on the actual offered IDs. Complete
candidate replay does not run for proper or dead prefixes. All294 prefix states
are finite engineering states of this single fixed declaration, not294 training
examples, independently reviewed laws or distinct source observations.

A bounded wrong sequence has status `rejected`, an empty `allowed_token_ids`
and a null completion requirement/candidate. Finite out-of-vocabulary integers
are retained verbatim with reason `out_of_vocabulary_id`; other wrong framing
or tokens use `prefix_mismatch`. Nothing is inserted, corrected or truncated.
`matched_prefix_length` records the exact initial match; `remaining_token_slots`
is512 minus the offered length. `completion_tokens_remaining` is293 minus the
length only for a valid prefix or complete sequence. There is no arbitrary
remaining-budget parameter and no global claim for another grammar.

The input must be an ordinary list of zero to512 plain integers strictly
between negative2^63 and positive2^63. Bools, floats, subclasses, foreign
containers, unsafe integers and a513th ID are API errors. Independent raw
context and complete codec pins are mandatory. Duplicate/nonfinite JSON,
altered frame/roles/sorts/counting policy, old537 codecs and resealed foreign
codecs are refused before lazy operation imports. A differently formatted
serialization of the same exact context is accepted only with its own raw-byte
SHA; the canonical context identity stays separate. The complete original input
is bounded at256KiB, context bytes at64KiB, codec metadata at32KiB and the whole
report at1MiB. Overflow refuses rather than selecting a subset.

The inspector snapshots only its own canonical producer, the fixed counted
owner and the known typed/parser source closure. Preloaded module origins are
checked before their filenames can direct any read. Caller and detached inputs,
genuine returned declarations/reports, canonical producer identity and complete
serialization remain fenced through the closing check. These checks are
sequential named-source custody, not arbitrary loaded-bytecode attestation or
an atomic operating-system snapshot.

`profile_is_singleton` is true and `admissible_content_count` is1. Every token is
forced independently of source text. `source_dependence_established`,
`permitted_inference_context_verified`, `numerical_runtime_available` and
`checkpoint_compatibility_verified` remain false. Context remains
`target_derived_authored_declaration`; authority flags stay false and both masks
are plain integer zero. A perfect singleton completion establishes no learned
reconstruction, statistical convergence, reviewed complete norm, governing
definition/use meaning, inference-context permission or Lean admission. The
existing head-spec v1 remains a checkpoint-free declaration without a numerical
prefix/scoring/serving runtime; this separate inspector does not promote it.

The [closed focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-prefix-inspection-20261022-01/qualification-summary.json) passed85 cases: 76 new owning controls, eight selected unchanged regressions and one retained-target observer. The294 offered-prefix states belong to one exhaustive engineering case; the retained-target observer supplies its separate existing293-ID label without reinterpreting or re-encoding its source. Original native/storage/source READ closed. This qualification binds its frozen source generation. It qualifies finite prefix mechanics only; no model, training, reviewed legal meaning, inference-context permission, complete norm, convergence or Lean admission follows. Existing170/249/79-case, native8/384/768/4096 captures and prior
BOS campaigns retain their original source and execution scope; no new model,
source encoding or Lean execution is reported by this guide.

#### Next implementation and acceptance order

First qualify a numerical implementation and serving contract compatible
with the existing peer spec and the separately validated transfer plan. Record
actual initialization, donor content/source pins, copied/fitted/new/unused
tensors, fresh optimizer state and complete-output budget through the existing
numerical owners. Preserve the 8D, 384D, 768D and genuine4096D producer/checkpoint
contracts. A metadata spec or plan does not instantiate a head or checkpoint.

In parallel, prepare a source-separated population with original physical
occurrences, independently pinned targets and context, alternatives,
grouping/dependency closure, review status and explicit exposure. Count distinct
content/context labels separately from physical occurrences and archival IDs.
A varied legal population needs a compatible broader target language; duplicating
this fixed frame across sources cannot supply it. Keep absent targets null and
learning/gold masks integer zero until the applicable review/admission contracts
supply the missing qualification.

The two ready native384 vectors commit complete284/242-byte heading-prefixed
local source candidates. The retained section7214 counted hypothesis commits a
different normalized163-byte operative occurrence. Their legal ID or a contained
text match establishes no source/context equality or target correspondence.
Do not relabel the native receipt or original target to make that join fit.
Reviewed complete norms, governing edition, entity/definition correspondence,
counting frame, purpose/permission/anaphora and per-use applicability remain
separate unresolved inputs.

Only after those contracts are supplied should a numerical consumer be qualified
in the existing training/runtime owners. Preserve complete BOS-generated outputs
and every refusal before a separate evaluator opens reference labels. Compare
against a source-independent constant baseline; keep source sensitivity and
role/modality/scope/condition errors separate from grammar completion. Authored
or weak-supervision experiments retain explicit exposure and non-gold status;
source review, reviewed training/gold, graph and Lean admission need their own
recorded decisions. This handoff grants no training or model-quality authority.
