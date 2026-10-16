# Retained decoder outputs and the next LegalIR training interface

This increment of the [US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
starts from `6b8b1346f888adbebbcf1d714e4ad0ab39a02052` and reuses the
[reconciled assets](legal_ir_asset_reconciliation_20261016.md).
The continuation passed **173 native test cases** and completed **60 generated
sequences plus 60 exact fresh-model replays**, with 3,240 forward steps. All sixty
first-pass outputs satisfy their retained grammar; all sixty remain unsupported
as richer relational requests. No training, legal review, teacher promotion or
Lean build follows from this validation.

The [evidence index](evidence/legal-decoder-output-integration-20261016/index-v02.json)
binds the source surveys, authored worker/configuration, frozen native requests,
readonly capacity observations and actual admission refusal. It contains no
checkpoint, latent, corpus or generated prediction payloads.
The [completed retry evidence](evidence/legal-decoder-storage-retry-20261016/index-v01.json)
adds native receipts, independent engineering audits and the exact startup
profile. Original failed/refused evidence remains unchanged.

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

## Completed numerical comparison

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

The initial numerical budget was one CPU slot, one child slot, 4 GiB sampled
resident accounting, 256 MiB storage and 1,800 seconds. A separate 16 GiB virtual
address-space ceiling and 1,200 CPU-second process limit do not increase the
native resident grant. The unchanged native owner supplies admission, startup
barrier, supervision, durable output sealing and release. The old nonnumerical
guard is not relaxed to permit Torch. No model download, encoder inference or
optimizer step was executed.

The installed `torch 2.13.0+cu130` imports CUDA library-discovery and optional
Dill file-type probes even though the numerical tensors and operations use CPU
float32. The first two numerical attempts stopped during this startup, before
decoder generation. A separately frozen startup profile raised **this replay's
process allowance from one to two**. It permits at most four exact
`/sbin/ldconfig -p` calls during Torch import, with fixed C locale, no shell/new
session/process-group changes and pinned wrapper, real executable and Dash
interpreter. The wrapper's `-p` branch skips package triggers and replaces itself
in the same PID. Known root-owned system aliases are checked explicitly.

The same startup window permits at most 32 writable standard-I/O probe opens on
the verified root-owned `/dev/null` character device `1:3`. It grants no regular
file output path. The completed run observed one allowed discovery call and five
writable null-device opens, with zero denied network or child-process attempts.
CPU, memory, storage and global policy remain unchanged; all other subprocesses
and persistent writes outside the native attempt remain denied.

The replay segment took 67.024 seconds; complete native execution took 154.143
seconds. These are validation timings, not an inference throughput benchmark.
Fresh-load agreement covers complete generation receipt digests, including raw
logit/prefix hashes and unchanged state, buffer, gradient and input checks.
The run recorded 814 checked source execution events from 49 distinct origins
(21 owned-checkout and 28 historical exact-path sources). All 21 private payload
files, totaling 2,397,930 bytes, remain in their durable native attempt.

| Correct-source variant | Primary exact stored target | Legacy exact stored target |
| --- | --- | --- |
| Original donors | 0/2 | 2/2 |
| Original 768D initialization | 0/2 | 1/2 |
| Aligned 768D initialization | 0/2 | 1/2 |
| Original-start trained interfaces | 0/2 | 1/2 |
| Aligned-start trained interfaces | 0/2 | 1/2 |

The primary rows are exposed validation; the two legacy rows are synthetic
training diagnostics. These repeated measurements are not ten independently
reviewed laws. Native grammar validity and EOS completion are 60/60 across all
variant/control observations, with no truncations or flagged canonicalization
changes; tagged decoding does not independently check canonicalization.

Cross-source inputs change no primary token sequence in this small panel. Zero
inputs change both primary sequences for the donor, aligned initialization and
aligned trained interfaces. All four student auxiliary heads keep their tokens
unchanged under both interventions, while the original legacy donor changes one
under zero input and both under cross-source input. Greedy-token invariance does
not establish that latent vectors or logits are unused. The result supplies a
specific discrimination/retention diagnostic, not dimensional superiority,
held-out accuracy or legal fidelity. No new weights were fitted or published.

## Storage history and native qualification

The following initial refusal is preserved as history; the completed retry below
supersedes its pending-execution status.

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
admission; at that point the numerical request had not been submitted. The retained/active
commitments, rather than the configured 160 GB named-root accounting cap, caused
this filesystem-capacity refusal.
The [native closeout](evidence/legal-decoder-output-integration-20261016/capacity-closeout-v02.json)
and [controller stderr](evidence/legal-decoder-output-integration-20261016/qualification01-controller-stderr.log)
retain the refusal and its exact original commitment. The revised numerical
request was prepared with 209 source pins, including the existing native scheduler
facade; the refused qualification request had 251. That original request remained
unsubmitted; the continuation used the separately versioned requests below.

`retained` is an accounting status, not permission to reclaim another owner's
reservation. The initial concrete options were additional filesystem capacity or
owner-led durable finalization of historical retained reservations after their
exact custody, liveness and retained-byte checks. At the initial refusal no ledger
or policy was changed, no foreign reservation was released and no weights,
corpora or evidence were deleted.

The selected qualification comprises the new compatibility tests and existing
lexical-output and tagged-codec tests. The new cases are authored receipt
consistency controls with uncomputed logit/state declarations; they do not attest
model execution. Both jobs initially awaited native admission. Source-only AST
and independent contract reviews remained separate from executed qualification,
and the PR stayed in draft pending the execution reported below.
The [independent source audit](evidence/legal-decoder-output-integration-20261016/source-helper-doc-audit-v02.json)
reviews the frozen adapter, 104 authored cases and numerical worker. It reports
source consistency only, and attributes the admission result to the root's
retained native refusal rather than claiming a second execution.

The later retry obtained native admission under the unchanged **160 GB campaign
cap**, after outstanding commitments decreased. The cap itself had not been
exceeded; increasing it would not have fixed the independent filesystem-free
check. Only the replay's process allowance needed to increase for the observed
startup helper described above.

The first admitted test attempt failed collection because its frozen source
roster omitted `legal_ir_family_evaluator.py` and `snapshot_evaluator.py`.
Adding their exact hashes resolved collection without changing product code.
The corrected 253-pin qualification executed 104 new compatibility cases, 32
existing lexical-output cases and 37 existing tagged-codec cases: **173 collected
= 173 successful calls = 173 unique JUnit cases**, with zero failures, errors or
skips and 21 checked product origins. The numerical job used 214 source/config/
system-file pins and completed all six declared checks.

Both successful native jobs sealed durable outputs, released their storage and
scheduler leases, closed with zero live group processes and reported null cleanup
errors. Three exact owned failed claims were reconciled after custody/liveness/
durability checks: 671,088,640 bytes of promises released, with all twenty files
and 268,890 bytes retained. No foreign reservation or policy was changed and no
payload was deleted. The numerical and qualification independent audits verify
the engineering receipts; they do not open prediction/model/corpus payloads or
grant semantic authority.

## Training work after this boundary is qualified

1. **Reuse the completed replay before fitting.** Preserve every generation and
   failure and diagnose the observed discrimination and auxiliary-retention
   gaps. Choose a retained initialization on declared
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
