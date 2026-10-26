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

## Normative target inspection APIs

The existing `logic/formalization/autoencoder/ir_cell_target_compatibility.py`
now exposes `inspect_normative_legal_ir_targets`, also delegated by
`checkpoint_hub`. It adds pure fixed-codec inspection for declared normative
384D/768D requests; `preflight_ir_cell_cached_targets` retains its original
source-pinned 384D cell contracts. No source cache or runtime was replaced.
The [historical original 190-case qualification](../../../../../docs/autoformalization/evidence/legal-ir-normative-target-binding-current-main-20261022.json)
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

The [historical original 229-case binding qualification](../../../../../docs/autoformalization/evidence/legal-ir-normative-target-binding-current-main-20261022.json)
records 229 cases / 687 passed phases, comprising the existing
190 controls and 39 added cases. Fixtures exercise all three genuine
public preparation routes. Arbitrary cache planning/validation and physical
source reads are genuine; native384 record admission alone uses declared
fixture records. Retained-cache historical native admission also uses its
existing fixture double. The qualification receipt preserves both failed attempts, the dependency-manifest
fix and the exact receipt-only privacy-assertion correction. No encoder attestation, retained-asset numerical result,
model restore/forward, optimizer update or legal review follows from these tests.

**Separate current-main integration, 2026-10-22:** the [new current-main run](../../../../../docs/autoformalization/evidence/legal-ir-normative-target-binding-current-main-20261022.json) passed **229 cases / 687 phases** over the same ordered authored fixture population. It used 190 actual selected-checkout source files, preserved nine newer public successors and checked 215 outer source pins. Original source READ, native resources and storage closed after verified cleanup. This is a new source integration result; the historical 190/570 and 229/687 results above retain their original generations. It adds no model reconstruction score, encoder attestation, reviewed statutory target, training eligibility or Lean authority.
