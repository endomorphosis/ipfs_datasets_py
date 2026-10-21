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
