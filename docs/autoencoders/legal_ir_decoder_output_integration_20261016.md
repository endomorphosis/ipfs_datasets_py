# Retained decoder outputs and the next LegalIR training interface

This increment of the [US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
starts from `6b8b1346f888adbebbcf1d714e4ad0ab39a02052` and reuses the
[reconciled assets](legal_ir_asset_reconciliation_20261016.md).
Its implementation and numerical replay are **pending native validation**.
No new training, model inference, legal review or Lean build has executed in
this increment. Source inspection and authored test cases do not establish
runtime correctness or higher autoformalization accuracy.

The [evidence index](evidence/legal-decoder-output-integration-20261016/index-v02.json)
binds the source surveys, authored worker/configuration, frozen native requests,
readonly capacity observations and actual admission refusal. It contains no
checkpoint, latent, corpus or generated prediction payloads.

## Output compatibility is the immediate gap

The retained GTE transfer lineages emit seven-facet deontic IR. They do not emit
the richer quantified relational request consumed by the current batch evaluator.
The new candidate-only companion
`logic/formalization/autoencoder/legal_ir_decoder_output_compatibility_v1.py`
preserves that distinction instead of inventing missing predicates, argument
roles, variable binders or encoder identities.

| Retained route | Existing output owner | Boundary |
| --- | --- | --- |
| Original 384D donor; 768D primary heads | `contextual_legal_ir_output.inspect_contextual_legal_predictions` with the exact stored lexical codec | Preserve generated rule order and the additional canonical-contract form separately. A normalization change is an observation, not an exact model output. |
| Original 8D formula donor; 768D auxiliary heads | `legal_formula_codec.decode_target` with the complete stored `legal-source-formula-codec/v1` asset | Preserve its original `typed-deontic-rule/v1` grammar and qualifier policy; a vocabulary-only reconstruction is not the original codec. |
| Rich relational batch evaluation | `legal_relational_batch_evaluation_v1` and `legal_relational_norm_v1` | Requires an actual typed request and a separately bound generation declaration. Native seven-facet syntax is insufficient. |

These are selected transfer-head lineages, not every decoder at a shared width.
The full sparse 8D state, linguistic bundle, contextual models, retained wording
states and detached F15/F17/F18 components retain their separate identities.
In particular, disabled-latent source-token components are not new 384D evidence.

The companion accepts independently pinned raw receipt, full codec and capture
descriptor bytes. Its descriptor connects an occurrence ID, source hash,
intervention label, actual head/variant/dimension, checkpoint hash and numerical
model/input hashes. Receipt consistency alone cannot verify those external assets
or authenticate execution. The adapter therefore always reports
`execution_authenticated=false`, false authority flags and zero training/gold
masks.

Raw generated IDs, actual BOS/EOS termination and truncation remain visible.
Interior special tokens and malformed grammar are never repaired. Native grammar
validity, completeness and canonicalization are reported separately from
`emitted_format_outside_relational_profile`. A decoded rule is not converted into
a relational request, and an unsupported format is not called a model abstention.
Capture descriptors intentionally have no fabricated encoder binding.

## Prepared numerical comparison

The private native worker reuses the existing source-only generator, retained
parent admissions, original and aligned loaders, intervention selection and
reference scorer. It selects two original exposed-validation rows and two legacy
training diagnostics. They are not four independently reviewed laws or a holdout.

The fixed comparison has five variants: original donors, original 768D
initialization, aligned 768D initialization, original-start trained interfaces
and aligned-start trained interfaces. Each receives source, zero and cyclic
cross-source vectors. All sixty first-pass sequences are saved before reference
scoring. Fresh private model loads then reproduce all sixty sequences and full
receipt digests, including per-prefix raw-logit hashes. Sequence counts and
actual autoregressive forward-step counts are distinct.

Historical manifests require their original implementation paths. The worker
uses those exact pinned historical training/helper paths without rewriting the
manifests; the new compatibility module is imported from the owned checkout.
Both source roots are physically checked. Fresh checked source buffers cover
normal imports and private `spec_from_file_location` aliases. Installed Torch
and its binary dependencies remain outside this source-integrity claim.

Parent admission reads reference-bearing provenance. The narrower guarantee is
that only source vectors and self-generated prefixes enter the numerical
generator, and generation/replay completes before reference scoring. It does not
claim system-wide denial of reference-file reads. Zero coordinates leave model
biases active and are not a disabled architecture branch.

The prepared numerical budget is one CPU slot, one child slot, 4 GiB sampled
resident accounting, 256 MiB storage and 1,800 seconds. A separate 16 GiB virtual
address-space ceiling and 1,200 CPU-second process limit do not increase the
native resident grant. The unchanged native owner supplies admission, startup
barrier, supervision, durable output sealing and release. The old nonnumerical
guard is not relaxed to permit Torch. No model download, encoder inference or
optimizer step is planned.

## Storage prerequisite and validation status

The qualified readonly storage observer reported zero headroom. At the subsequent
metadata snapshot, 21,442,281,472 bytes were available; 92 retained reservations
committed 33,178,031,680 bytes, and one active reservation committed 8,388,608
bytes. The additional 256 MiB replay therefore needed approximately 12.01 GB
more available capacity at that snapshot. A 13 GB increase provides a small
margin, subject to a fresh native admission check.

The later actual native admission refused the 128 MiB qualification request at
`owner.open`, before a durable reservation, scheduler lease or child started.
Its available-space observation had fallen to 19,653,750,784 bytes and reported
a 13,666,887,232-byte free-space deficit for that test request. The 256 MiB
numerical request would have needed 13,801,104,960 additional bytes at that
snapshot. Plan for at least 15 GB of restored capacity, then obtain fresh native
admission; the numerical request has not been submitted. The retained/active
commitments, rather than the configured 160 GB named-root accounting cap, caused
this filesystem-capacity refusal.
The [native closeout](evidence/legal-decoder-output-integration-20261016/capacity-closeout-v02.json)
and [controller stderr](evidence/legal-decoder-output-integration-20261016/qualification01-controller-stderr.log)
retain the refusal and its exact original commitment. The revised numerical
request is prepared with 209 source pins, including the existing native scheduler
facade; the refused qualification request has 251. The numerical request remains
unsubmitted.

`retained` is an accounting status, not permission to reclaim another owner's
reservation. The concrete options are additional filesystem capacity or
owner-led durable finalization of historical retained reservations after their
exact custody, liveness and retained-byte checks. This work has not edited the
ledger, changed policy caps, released foreign reservations or deleted weights,
corpora or evidence.

The selected qualification comprises the new compatibility tests and existing
lexical-output and tagged-codec tests. The new cases are authored receipt
consistency controls with uncomputed logit/state declarations; they do not attest
model execution. Both the test job and numerical job require native admission.
Source-only AST and independent contract reviews are recorded separately from
executed qualification. Keep this change in draft until execution is available.
The [independent source audit](evidence/legal-decoder-output-integration-20261016/source-helper-doc-audit-v02.json)
reviews the frozen adapter, 104 authored cases and numerical worker. It reports
source consistency only, and attributes the admission result to the root's
retained native refusal rather than claiming a second execution.

## Training work after this boundary is qualified

1. **Replay before fitting.** Complete the prepared comparison and preserve every
   generation and failure. Choose a retained initialization on declared
   development criteria; do not select favorable control subsets or repeat the
   full historical 930-generation diagnostic merely to produce another score.
2. **Freeze the target contract.** Use reviewed complete provisions and their
   permitted context to declare typed predicate signatures, ordered arguments,
   quantifier/modality scope, exceptions and governing definitions. Preserve
   unavailable or unsupported targets. A compiler-derived cache target can be
   engineering supervision with explicit origin; it cannot become reviewed gold
   through agreement with another compiler.
3. **Train an actual structured output head.** Reuse compatible encoder/input
   adapters and decoder bodies, but register a new head/codec when the output
   language changes. Generate typed AST actions and source-bound symbol/mention
   pointers with arity, variable-scope and type checks. A deterministic serializer
   can then emit supported logic-family syntax. It must refuse missing operators
   rather than erase their meaning to fit an older grammar.
4. **Measure the two architectural contributions.** Compare source-only,
   latent-only and source-plus-latent variants with matched initialization,
   freeze masks, optimizer budgets and targets. Evaluate 8D, 384D and 768D as
   independent input contracts. Correct/zero/permuted vectors test conditioning;
   a source-pointer channel measures a distinct route and must be declared.
   Warm-start only tensors whose vocabulary, shape and semantic roles match.
5. **Train for semantic attachments and free generation.** Begin with token/action
   loss on eligible targets and explicit rule/argument/qualifier supervision.
   Add reviewed hard negatives for role reversal, misplaced negation, wrong
   definition scope and dropped exceptions. Teacher-forced training loss remains
   a training diagnostic. Evaluate ordinary target-free generation, complete
   rules and all selected occurrences, including missing/invalid/unsupported
   outputs; report comparable-reference denominators separately.
6. **Preserve the graph and Lean gates.** Aggregate only explicitly supported
   source-bound assertions into versioned term senses, definitions, entities and
   norms. Resolve each physical use under its actual governing scope; equal
   labels do not imply the same entity. Deterministically lower supported typed
   structures into shared Lean modules with declared assumptions. Require actual
   `lake build legal`, complete expected outputs and meaningful positive/negative
   consequences before claiming the component builds. Compilation and model
   agreement still do not establish fidelity to the law.

This advances the existing roadmap's asset/runtime and decoder-interface work.
The reviewed connected-component, broader operator support and coherent graph/
Lean release remain the existing independent prerequisites, not side effects of
successful seven-facet decoding.
