# Cached contextual LegalIR reconstruction

The explicit contextual runtime restores the original selected LegalIR 384D or
768D state and generates from the original cached paragraph and ordered clause
vectors. It preserves the original raw384 donor, codec, preprocessing, frozen
projection buffers and full selected tensor inventory. It does not fit a new
normalization or count prior, regenerate embeddings, train a decoder or use a
gold prefix. This is an opt-in development replay capability; ModelManager
registration and production runtime qualification remain separate.

## Executed original-asset regression

The October 6 qualification ran both lanes from frozen source commit
`37c2d63f0bf9490e5b019788afcafbc3b806d8c7`. Generation and reference evaluation
ran in separate processes. The original states, cached inputs, CPU RNG and saved
normalizations remained unchanged. Every new token/status/EOS sequence matches
the predictions in the byte-authenticated historical candidate reports.

| Measured observation | LegalIR384 | LegalIR768 |
| --- | ---: | ---: |
| Complete EOS candidates | 48/48 | 48/48 |
| Ordered semantic IR exactness | 48/48 | 48/48 |
| Native canonical contract exactness | 48/48 | 48/48 |
| Rules preserved, with no extra/missing rules | 180/180 | 180/180 |
| Actor/action/modality/object fields | 720/720 | 720/720 |
| Source-withheld canonical text outputs | 48/48 | 48/48 |
| Original text UTF-8 byte equality | 0/48 | 0/48 |
| Original text NFC/whitespace equality | 0/48 | 0/48 |

Conditions, exceptions and temporal fields also agree, but every reference
qualifier is empty. This is an exposed authored regression panel with one, two,
four and eight literal clauses. It does not test fresh source groups, nonempty
qualifiers, broad legal meaning or 8192-token spans.

The parallel [paraphrase modality diagnostic](paraphrase_modality_diagnostics.md)
on other selected states/cohorts reports 20/48 and 19/48 exact 384D paragraphs,
and 46/48 for each 768D arm. Most modality errors already occur in the source
head; lower TRAIN loss did not repair them. Those results and this 48/48 original
contextual regression have different checkpoint and source populations. Preserve
both experiments, and use their explicit asset/cohort joins when choosing the
next ablation. A good score on the original wording panel does not qualify a
teacher for alternate wording or richer qualifiers.

For example, the original text is `The registrar is allowed to preserve the
archive.` The generated semantic IR is exact, while the source-withheld renderer
produces `Registrar may preserve archive.` This concrete pipeline recovers its
specified semantic representation, but its current deterministic text baseline
does not recover the originating prose. No trained prose decoder was loaded in
this comparison.

The [generation receipt](evidence/contextual-legal-runtime-20261006/generation-qualification.json),
[separate evaluation](evidence/contextual-legal-runtime-20261006/separate-evaluation.json)
and per-lane candidate/IR/text reports retain the full measurements. The
[qualification driver](evidence/contextual-legal-runtime-20261006/qualify_original_assets.py)
binds both actual dimensions, original checkpoint/cache/donor pins and immutable
historical candidate hashes. During generation it blocks optimizer construction,
fitting helpers, historical training imports, reference/evaluation-file reads,
encoder/database imports and network operations. The evaluator is Torch-free.
All 44 previously surveyed original files remain unchanged after the run.

The final checks passed **244** contextual/source-value controls and **210**
existing numerical-owner regressions. Independent reviews cover metadata
admission, numeric restoration, output measurements, source custody and the
qualification driver. These checks do not promote native profile, teacher,
production runtime, holdout or proof authority.

To reproduce locally, copy the retained driver and its `source-survey` folder to
a new output directory, preserving these original receipts. Run its `generate`
phase with `--repo` pointing to the intended checkout, then run `evaluate` in a
separate process. The original asset pins must resolve; a public checkpoint alone
does not replace the original source/context caches. Configure
`IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` and `IPFS_DATASETS_AUTO_INSTALL=0` as in the
recorded run.

## What reconstruction measures

The output owner reports three different observations:

| Observation | Comparison | Information retained |
| --- | --- | --- |
| Ordered semantic IR exactness | Generated seven-field rule document against the reference document | Original generated rule order and qualifier multiplicity |
| Canonical contract exactness | Actual `CanonicalRoundTripIR@1` payloads | Contract sorting of rules and sorting/deduplication of qualifiers |
| Original text exactness | Text rendered from generated IR against originating source text | Separate UTF-8 byte equality and NFC/whitespace equality; case, punctuation and word order remain significant |

Syntax validity requires actual canonical rule conformance. A complete candidate
also requires a consistent EOS receipt within the output budget. A valid JSON
document without EOS remains incomplete. Missing predictions remain failed rows
in fixed reference denominators. Malformed/deadline outputs remain errors, extra
generated rules are counted, and unknown or duplicate prediction identities are
rejected.
Canonical contract agreement does not establish equivalent legal meaning.

The source-withheld text path uses the existing deterministic
`SourceWithheldCanonicalDecompiler`. It receives only generated canonical IR and
a request identity. Original prose, lexical residuals and reference IR are not
inputs to that owner. Its rendered text is a measurable baseline, not a trained
original-prose decoder. The semantic checkpoint is not relabelled as a prose
checkpoint.

## Explicit interfaces and original asset selection

`ipfs_datasets_py.logic.formalization.autoencoder.contextual_legal_ir_runtime`
exports `prepare_contextual_legal_ir_runtime` and
`open_contextual_legal_ir_autoencoder`. Preparation is standard-library-only.
Opening lazily restores the fixed CPU numerical owner; its returned object
provides `describe()` and `infer_cached()`.

Both functions accept the same closed request and explicitly pinned assets:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.contextual_legal_ir_runtime import (
    prepare_contextual_legal_ir_runtime,
    open_contextual_legal_ir_autoencoder,
)

request = {
    "ir_family_id": "legal_ir",
    "dimension": 384,  # Select 768 for its separate retained state/cache lane.
    "dimension_role": "input_embedding",
    "task_id": "semantic_IR_reconstruction",
    "checkpoint_sha256": checkpoint_pin["sha256"],
}
options = dict(
    checkpoint_pin=checkpoint_pin,
    preprocessing_pin=preprocessing_pin,
    donor_checkpoint_pin=original_raw384_donor_pin,
    source_inputs_pin=source_only_inputs_pin,
    source_contexts_pin=source_only_contexts_pin,
    source_owner_pins=current_thirteen_source_owner_pins,
    row_ids=ordered_selected_source_ids,
)
plan = prepare_contextual_legal_ir_runtime(request, **options)
# The explicit numerical caller configures the existing CPU protocol.
import torch
torch.set_num_threads(1)
decoder = open_contextual_legal_ir_autoencoder(request, **options)
generated = decoder.infer_cached()
predictions = generated["raw_candidate_report"]["predictions"]
```

Each pin has exactly `path`, `bytes` and `sha256`. Paths must identify canonical,
single-link regular files. `SOURCE_OWNER_NAMES` defines the exact thirteen
current library owners to pin; this includes the new facade/numerical owner and
eleven existing numerical owners. Ten historical owners remain byte-identical.
The eleventh moves its unused training-helper import inside its training-only
function; its numerical calculations are unchanged.

The selected complete state contains 32 tensors/buffers. Its donor has 13. The
facade checks their serialized and typed-byte hashes, dimensions, codec, saved
native initializer, frozen projection values, normalizations, source binding
and context inventory before numerical loading. Numerical restoration repeats
geometry/state checks and loads every selected entry strictly. Source files and
asset identities are checked after restoration and around inference; repeated
endpoint checks are not an atomic cross-file snapshot. A late refusal retains
raw candidates only as diagnostics with truthful call-boundary flags.

This version replays the retained validation source inventory, allowing an
explicit ordered selection of its rows. Rehashed foreign vectors, relabelled
source rows and substituted context packets fail the saved inventory joins.
Inputs contain exactly `id`, `source_text` and `input`, with separately bound
literal-clause descriptors; they cannot contain target IDs, labels or gold IR.

The saved TRAIN paragraph transform runs once on raw paragraph/clause vectors.
Clause vectors are then padded to eight slots with a source-derived boolean
mask. The decoder's saved paragraph and clause feature normalizations remain
separate internal stages. No padding, clause count or normalization comes from
evaluation targets. The output budget is 512 tokens including BOS/EOS. The
32-token vocabulary is not a 32-token output limit. No 8192-token experiment is
qualified by these caches.

`contextual_legal_ir_output` separately exports
`inspect_contextual_legal_predictions`, `score_contextual_legal_predictions`,
`render_contextual_legal_text_candidates` and `score_legal_text_reconstructions`.
The evaluation functions consume persisted candidates and independent reference
rows after generation. See the retained qualification driver and receipts below
for an executable original-asset example.

## Improvement sequence

1. Preserve this original-asset regression as the baseline. Freeze source groups
   for a fresh holdout before further selection or fitting. Include alternate
   wording, nonempty conditions/exceptions/temporal qualifiers, negation,
   conflicting modalities, duplicate clauses and reordered clauses. Keep
   source-group boundaries across train, tuning and final evaluation; report
   ordered exactness, per-facet coverage, refusals, EOS and original-text metrics
   by span size. Training loss alone does not identify a saturated decoder.
2. Compare paragraph-only, paragraph-plus-clause and clause-only conditioning on
   matched rows, donor weights and output budgets. Add order/mask/vector controls
   that measure dependence on source inputs. Use the
   [frozen modality diagnosis](paraphrase_modality_diagnostics.md)
   from the parallel session when defining modality ablations. Preserve that
   session's source/checkpoint/evaluation provenance instead of mixing its
   scores with this contextual panel.
3. Define `legal_text_reconstruction` as its own decoder task. Semantic IR omits
   wording choices, so exact arbitrary prose recovery requires an explicit
   information contract: retain lexical anchors/residuals, or optimize a reviewed
   semantic paraphrase objective. Include a semantic-only ablation and account
   for every retained residual byte/token, including original clause order,
   punctuation and citation spans. Compare ordered-IR and canonical-IR rendering
   explicitly. Evaluate source collisions that share
   one semantic IR but have different original text. Publish byte, normalized
   text and reviewed legal-meaning scores independently.
4. Warm-start compatible 768D decoder tensors from the authenticated 8D/384D
   decoder donors. Declare incompatible input, clause and output heads and
   projection/adaptor contracts explicitly. Record a tensor transfer manifest
   with names, shapes, dtypes and codec/token mappings before copying weights.
   Reuse saved labels, splits, codecs
   and the existing width-specific embeddings; do not pad a 384D vector and
   claim it is a native 768D GTE embedding. Align examples by source identities.
   If paired 768D vectors are missing, record that inventory gap before extending
   the cache. Compare reused tensors alone, teacher-output distillation and an
   explicitly documented random-initialization control. Distill each decoder
   task separately after its relevant held-out gates pass.
5. Increase encoder-span and decoder-output budgets independently, with a span
   curriculum and separately authenticated producer receipts. The native768
   declaration can support a later 8192-token lane, but current cached512
   experiments do not test it. Assess cross-clause references, qualifier scope,
   rule ordering and long-span truncation explicitly before promoting that lane.
6. Keep CodebaseIR, SecurityIR, LegalIR and IntentIR distinct at 8D/384D/768D.
   Maintain separate family/width inventories, physical DuckDB/DuckLake stores
   and Hugging Face repositories. Inside each lane, index checkpoints by output
   schema/version, decoder task, run/ablation and immutable asset hash; give FOL,
   TDFOL and original-text heads their own task contracts. An existing unknown
   schema/profile identity remains unknown until its native owner is qualified.
7. Bind repository scans to the tested commit, dirty-content generation, file
   hashes and source spans. Autoencoder-produced CodebaseIR and logic projections
   enter the candidate index with producer/checkpoint/profile identities. Store
   checker status, backend/version, assumptions and dependency hashes separately
   in the proof index. Invalidate dependent entries when code changes. IntentIR
   matching and the supervisor symbolic planner consume current checked entries
   and explicit candidate/refusal states; successful decoder reconstruction does
   not turn a candidate into a proof.
8. Treat on-the-fly CodebaseIR training as a new run in the codebase-specific
   inventory. Pin the repository generation, reused teacher/checkpoint assets,
   width-specific caches, split boundaries and new optimizer state. Continue
   planning against the prior admitted generation while the candidate run is
   evaluated. Promotion requires current-source evidence and the matching native
   task/checker gates; it must not mutate a sealed planner context or reuse stale
   catalog/proof generation identifiers.

For supervisor registration and immutable public model locations, see
[contextual checkpoint recovery](https://github.com/endomorphosis/ipfs_accelerate_py/blob/main/docs/agent_supervisor/contextual_ir_checkpoint_recovery.md).
Both restored lanes retain false teacher, native-profile, production-runtime,
fresh-holdout and proof authority flags. This increment supports original cached
LegalIR384/768 replay; it does not supply new 8D or other-family numerical routes.
