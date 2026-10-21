# Relational decoder targets and source-only examples

This increment follows the [retained decoder replay](../../../../../docs/autoencoders/legal_ir_decoder_output_integration_20261016.md)
and completed component registration (`../autoencoders/evidence/legal-ir-missing-component-import-20261016/README.md`; historical reference unavailable in this checkout).
The replay's outputs satisfy their old seven-facet grammar but do not implement
the richer relational request. Its two exposed primary references remain 0/2
for every variant. This contribution prepares a separately versioned target
interface; it creates no trained decoder or improved reconstruction score.
It supplies a reproducible target boundary for the parallel
[span-to-graph-to-Lean execution design](../../../../../docs/autoencoders/legal_ir_span_graph_lean_execution_plan_20261016.md).
That design's proposed AST-action head remains separate from this byte codec.

## Existing owners and the new boundary

`logic/formalization/autoencoder/legal_relational_target_codec_v1.py` serializes
the existing `legal-relational-norm-request/v1` through `TypedLogicCodec@1` and
the public [relational norm owner](legal_relational_norm_v1.md). It introduces
no new AST, legal interpretation, lowerer or reconstruction evaluator.

The codec is a **fixed byte serialization**, not a semantic action language or
a grammar-constrained numerical head. Its 259 entries are PAD=0, BOS=1, EOS=2
and UTF-8 byte values at IDs 3–258. The complete vocabulary is fixed before any
target is supplied. Each target keeps the complete validated expression,
including signature, artifact IDs, ordered arguments, binders, modal payloads
and the ordered role ledger. Original transport hashes and canonical target
hashes remain separate. Canonical JSON preserves decoded values and all array
order; transport whitespace, key ordering and escape spelling may differ.

Supported targets retain the existing authored profile: `tdfol/tdfol_default`
at namespace version 1.0.0, one `Object` carrier plus `Bool`, explicitly bound
variables, declared predicates, binary connectives, negation, quantifiers and
the existing O/P/F extension. Equality, constants, functions, counting, richer
sorts and temporal operators require different supported profiles. The counted
frame owner remains separate. Nothing is erased or converted into an opaque
atom to force an unsupported target through this codec.

Candidate decoding accepts generated IDs and an independently committed codec;
it has no reference argument or target lookup. It retains framing and original
generated transport, refuses complete bound overflow, and preserves rejected
or incomplete candidates without repairing EOS, UTF-8 or typed structure.
A syntactically valid candidate remains unreviewed. Exact serialization of
artifact IDs is a transport measurement; the existing
[structural and alpha comparisons](legal_relational_reconstruction_v1.md)
remain the appropriate separate diagnostics for meaning-bearing structure.

Output length is canonical UTF-8 byte count plus two control IDs. It is not
encoder-token count. The 524,288-byte request bound and 524,290-ID sequence bound
are integrity limits, not evidence that a retained decoder supports that length
or that an input fits a 512-token or 8,192-token encoder profile. Those budgets
must be checked against their own tokenizer, input producer and checkpoint.

## Source, labels and provenance

`legal_relational_decoder_example_v1.py` replays the complete original
[source-to-typed correspondence](legal_source_typed_norm_join_v1.md) before
exporting three separate compartments:

| Compartment | Contents and boundary |
| --- | --- |
| `model_input` | The unchanged validated `scope_request`: source text and its explicitly declared context. No candidate AST, target roles, alternative ID, Lean text or review packet. |
| `label` | Original independently pinned relational request transport, original report hash and fixed-codec encoding. Source-only pending cases keep this null. |
| `provenance` and bindings | Physical source identity, component/alternative, unresolved issues, context obligations, caller-declared exposure and optional embedding-cache reference. These are separate from the model prompt. |

The physical grouping key binds original HTML hash, source version, coordinate
system, character/UTF-8 boundaries and span hash. Changing an interpretation,
component label or embedding lane does not turn the same physical source into
an independent example. The two retained §7213 hypotheses therefore remain
competing exposed alternatives, not separate held-out laws. Broader connected
component and version grouping remains the partition owner's responsibility.

An optional embedding reference preserves a cache key, producer/profile IDs,
dimension 8/384/768, declared token limit, payload size/hash and the exact
source/context input hash. This adapter opens no embedding file, regenerates
no vector and authenticates no producer. Numerical consumers must validate the
actual retained payload and its full input profile before reuse. No width alone
establishes compatibility, and detached source-token components are not active
embedding lanes.

Every example has an unassigned split and zero training/evaluation-gold masks.
Exposure is caller-declared `exposed` or `unknown`; no blind status is inferred.
The existing eligibility and review owners remain authoritative. Source custody,
complete node correspondence and successful codec replay do not establish legal
meaning, independently reviewed labels, a teacher, training admission, graph
admission or Lean authority. The inspected source/review workflow has not yet
established an eligible reviewed statutory target population.

## Public interfaces

The codec exposes:

- `build_relational_target_codec_v1()` and `relational_target_codec_sha256(codec)`.
- `encode_relational_target_v1(request_raw, *, expected_request_sha256, codec, expected_codec_sha256)`.
- `decode_relational_candidate_v1(generated_ids, *, codec, expected_codec_sha256)`.
- `relational_target_encoding_sha256(report)` and complete original-input
  `validate_relational_target_encoding_v1(...)`.

The example adapter exposes
`prepare_relational_decoder_example_v1(join_report, example_request_raw, *, expected_example_request_sha256, expected_join_report_sha256, join_replay_inputs, codec, expected_codec_sha256)`,
its complete-report hash and a full original-input replay validator. The replay
inputs are the existing join preparation call by name, including all original
source/scope and optional relational transports and independent commitments.
Hashes must come from retained caller manifests; resealing a changed report
cannot authorize promoted masks, target leakage or altered source identity.

The closed example request contains `schema`,
`task_id="typed_relational_IR_reconstruction"`, `exposure_status` and
`embedding_reference`. No admission or split switch is accepted. Both modules
load standard-library code at public import and check their trusted operation
sources around replay. They start no resource owner; execution remains subject
to the caller's existing resource lifecycle.

## Reusing learned decoders

Keep the previous seven-facet and legacy formula heads, codecs and checkpoints
intact. A future structured head needs a separate family/schema/task/profile/
format/codec identity for each active input contract. The new byte vocabulary
does not make old token logits interchangeable or authorize sequence KL across
different vocabulary orders.

Build a tensor reuse ledger before fitting: exact donor checkpoint and runtime,
parameter name/shape/semantic role, copied/frozen/fitted/new disposition and
initializer lineage. Reuse compatible learned decoder bodies, source adapters
and the later fitted interfaces, with their existing cached embeddings. A new
output layer must declare its own initialization and training; shared width
alone is insufficient to copy it. Preserve independent 8D/384D/768D paths and
keep detached F15/F17/F18 source-token components separate.

Measure complete target lengths and artifact-identity overhead before selecting
the numerical head's output budget. A later compact semantic-action codec is a
separate versioned task; it must preserve the same ordered typed meaning and
explicit identity correspondence. This byte contract establishes a reproducible
serialization boundary, not an efficient or trained generation architecture.

The replay's auxiliary retention drop appears in both 768D initializers before
interface training: native legacy donor 2/2 versus initializer/student 1/2.
The copied legacy decoder is reached through
`auxiliary_connector(shared_condition)`, while aligned initialization fits the
primary boundary and leaves that connector unfitted. The next numerical
diagnostic should compare original cached 8D input, shared condition,
connector-produced 8D input and identical-prefix legacy logits, with an
explicitly labelled original-input bypass. Diagnose conditioning and retention
separately before attributing the difference to forgetting.

Freeze source identity, prefix and vocabulary order for each comparison.
Measure logit changes and target margin/NLL alongside greedy-token changes;
unchanged argmax does not establish unused latent information. Correct/zero/
cross-source controls remain distinct, and zero input leaves biases active.
Use the existing completed 60+60 replay as the baseline; only new diagnostic
observations justify further numerical work.

Before selecting a numerical head, freeze a finite example inventory with the
complete candidate, pending and unsupported populations; physical-source and
connected-component groups; conflicting alternatives; declared exposure; and
canonical target byte lengths, including artifact-identity overhead. Keep the
adapter's masks zero. An explicitly scoped engineering-supervision policy and
the existing review/admission owners must govern any later label use. Review
the tensor reuse and route/codec compatibility ledger against that inventory
before fitting.

Reuse the existing [batch evaluator](legal_relational_batch_evaluation_v1.md)
for selected-population coverage. A new byte-preserving inference bridge is
still required: its current prediction intake accepts UTF-8 request strings,
whereas this codec also records invalid UTF-8, framing and incomplete outputs.
Keep those actual outcomes and original IDs/bytes without manufacturing an
empty request or relabelling a failure as abstention. This bridge must extend
the existing accounting path rather than create another denominator owner.

The [corpus improvement plan](../../../../../docs/autoencoders/legal_ir_uscode_corpus_improvement_plan_20261015.md)
continues to require reviewed typed targets, source/target separation, complete
selected-population evaluation and scoped graph/Lean gates. Codec round-trip
and candidate example preparation supply none of those semantic decisions.

Native attempt02 passed **142 unique cases** across the two new complete modules
(36 codec and 36 example cases) and all 70 existing relational-owner cases.
Collection, successful calls and JUnit populations agree, with no failures,
errors or skips. Its checked-buffer worker used 255 exact source pins, verified
104 product origins and recorded zero network or extra-process attempts. The
qualification receipt elapsed time is 22.428740442031994 seconds. The unchanged
native parent completed durability, drained the process group, and released
storage and its lease with no cleanup error. The separate administrative run
passed the same 142 cases; these counts overlap and are not corpus coverage.

Attempt01 remains failed: pytest's ancestor package setup tried to import the
checkout root under its basename `datasets`, and the SDK guard refused it before
any test calls. Attempt02 adds only an explicit collection boundary at the common
selected test directory. All product/test bodies, complete selected files,
assertions, guards and resource limits remain unchanged. The exact failed claim
was reconciled through the existing public recovery owner, retaining ten files
totaling 984,985 bytes and releasing 134,217,728 bytes of reservation accounting.
No failed result is promoted. The evidence index (`../autoencoders/evidence/legal-relational-target-contract-20261016/README.md`; historical reference unavailable in this checkout)
records the reuse, reviews, failure and native closeout. No corpus payload,
checkpoint, embedding, inference, training, human review or Lean build ran in
this qualification.
