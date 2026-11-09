# Authored counted-frame profile v1

This profile represents **at most three distinct objects in each explicitly declared event/time frame**. It is a small, unreviewed formal declaration. It does not determine the intended meaning of a statute.

For arbitrary sorts `Object`, `EventFrame` and `TimeFrame`, and a caller-declared relation `Member : Object × EventFrame × TimeFrame → Bool`, the formula is:

```text
forall event, time, x0, x1, x2, x3.
  (Member(x0,event,time) and Member(x1,event,time)
   and Member(x2,event,time) and Member(x3,event,time))
  -> (x0=x1 or x0=x2 or x0=x3 or x1=x2 or x1=x3 or x2=x3)
```

Each quantifier has an explicit sort. Equality is the existing typed AST's built-in object identity, not an uninterpreted predicate. All four membership atoms share the same event and time variables. Connectives have a fixed binary left-associated representation. The complete expansion has 49 physical nodes, six quantifiers, four membership occurrences and six equality occurrences.

The formula allows zero, one, two or three distinct members. Duplicate occurrence rows do not increase the count. Separate event frames and time frames have separate limits. `TimeFrame` is an arbitrary index: this profile introduces no ordering, calendar, duration, simultaneity or native temporal semantics. It does not assert a global, lifetime or cumulative cap, select the legal unit of counting, or supply a domain-specific meaning of `Member`.

## Public use

Import `ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1`. The module's ordinary import uses the standard library; syntax owners load after bounded, duplicate-free request validation.

```python
import hashlib
import json
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted

request = counted.authored_counted_frame_request()
raw = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode()
request_sha256 = hashlib.sha256(raw).hexdigest()
report = counted.prepare_counted_frame(raw, expected_request_sha256=request_sha256)
counted.validate_counted_frame(
    report, raw,
    expected_request_sha256=request_sha256,
    expected_report_sha256=counted.counted_frame_report_sha256(report),
)
```

The constructor supplies an authored example, never a source-derived target. Requests must explicitly declare the fixed maximum, distinctness rule, frame, argument roles, variable names, complete typed expression and null source binding. Missing declarations, additional fields, other bounds, altered binder/argument order, unsupported syntax and noncanonical expression serialization fail closed. Report validation replays the exact original request and regenerates the complete report, including generated text and trusted producer identities. Offered producer paths do not select files to read.

## Qualification boundary

The profile reuses the shared typed AST, elaboration, canonical FOL printer/parser and alpha-equivalence check. A narrow local printer subclass explicitly parenthesizes binary conjunctions and disjunctions: the shared default printer otherwise flattens their textual grouping, and reparsing creates n-ary nodes. Every other printing case delegates to the shared printer. The original 49-node tree is alpha-compared with both parses, and grouped printing must remain stable. Parsing produces fresh node IDs and ranges, so its structural comparison uses alpha-equivalence rather than byte identity. Original request and typed-expression identities are retained separately.

The existing native TDFOL route has no equality formula constructor/rendering branch. This profile consequently uses canonical FOL syntax and a specialized Lean text template for this one recognized formula. Lean text uses actual `=` and a parameterized membership relation. It needs no `Finset`, `DecidableEq`, Mathlib or finite-domain assumption. No Lean build, kernel check, proof, native TDFOL parse, theorem validity or legal fidelity is implied by text generation or finite controls.

Retained finite controls independently interpret the typed formula. Three versus four distinct members, duplicate rows, different events, different times, unrelated objects, zero/two members and each of the six equality-pair witnesses detect specific representation mistakes. They are illustrative authored controls, not a general proof or independent statutory evaluation set.

## Relationship to the corpus plan

The existing source-counted join v2 now preserves this profile as a separate partial correspondence, with its frame, equality, sorts, source dependencies and unresolved assumptions. The original relational APIs retain their contracts. The separately qualified unsigned counted-review owner retains the proposal for review; neither route supplies an accepted complete norm, signed subject or source-linked lowering authority.

The sampled §7214 paragraph has a separately qualified partial counted proposal and unsigned review packet. Its counting unit/frame, permission scope, assignment restriction, purpose, pronoun and entity/definition correspondence still need supported decisions and independent review. §7213's two partial alternatives remain unreviewed. No accepted meaning, governing-definition edge, review signature, graph/cache/corpus/Lean admission or training/evaluation gold is created here. Training and evaluation masks remain zero.

The fixed training review remains the basis for learned work: F18 is scientific failure/no promotion; F19 is the saved-score diagnostic; the separately reported auxiliary embedding epoch is not formula-decoder training. This mechanical profile adds no training, rescoring, inventory refresh or new formalization control.

## Canonical recovery and separate native evidence

The owner and its authored tests were recovered from commit `2b9f325a080001272ac6dd3949cff5a4566281eb`; this guide now lives beside them in the canonical autoformal module. The [later qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-frame-adoption-20261021-01/qualification-summary-v02.json) records 109 migration controls and one separately owned successful actual Lean build case, with original native, storage and source READ closeout. The first cohort passed all 109 migration controls but its native case failed because the Lake project omitted the generated definition module from its roots. That failure and its outputs remain retained; their storage reservation was released separately through the original recovery owner. The successful native case belongs to a separate corrected-project retry, without rerunning the 109 migration controls. There were two actual native build attempts, one retained failure and one success. The historical 277-case qualification and its zero-build boundary remain unchanged. These later executions have their own source generation and are not added to that historical cohort.

The preparation report still records `native_build_executed: false`. The separate actual build witness compiles the exact emitted definition and observes these three constructive authored theorems:

- `CountedProofs.empty_relation_holds`
- `CountedProofs.subrelation_preserves_bound`
- `CountedProofs.four_distinct_excluded`

They establish the empty-relation case, preservation under a subrelation when the larger relation satisfies the bound, and exclusion of four pairwise-distinct members under the bound premise. The retained axiom observations belong to that actual native witness. Compilation and these conditional properties do not establish that an arbitrary `Member` relation satisfies the cap or that this frame expresses a statute.

The profile remains authored and unreviewed, with null source binding and zero training/evaluation-gold masks. Section 7214 retains an unreviewed partial counted proposal: complete norm semantics, counting unit/frame, legal identity, permission/purpose/anaphora, scoped entity/definition bindings and supplied source/meaning/per-use applicability decisions remain open. No new native type, model inference, training, source-to-model equivalence or convergence is qualified.


## Counted content and lexical round-trip v1

The same owner now has an additive, counted-specific archival transport. It
supports exactly the already recognized fixed authored frame. The existing
Object/Bool compact-content v1, fixed 537-token head, normative32 checkpoints,
pointer consumers and their source pins are unchanged. A broader AST, byte
alphabet or equal vector width does not make those consumers compatible with
this counted profile. No numerical checkpoint or learned generator is added.

The counted content has schema `legal-counted-compact-content/v1` and contains
only `schema` and `tree`. Its constructors are:

| Node | Representation |
| --- | --- |
| Bound variable | `["variable", binder_index]` |
| Membership | `["predicate", 0, [object_term, event_term, time_term]]` |
| Built-in equality | `["equality", left_term, right_term]` |
| Quantifier | `["forall", binder_index, sort_name, body]` |
| Binary connective | `["and" / "or" / "implies", left, right]` |

Indices are quantifier preorder indices 0 through 5. Quantifiers retain
`EventFrame`, `TimeFrame`, then four `Object` sorts; all 49 nodes, six binders,
four ordered memberships, six ordered equality pairs and binary grouping must
match the existing frame. This is a closed fixed grammar, not a general
many-sorted decoder or an alpha-renaming extension. Binder names remain the
original fixed `event`, `time`, `x0`, `x1`, `x2`, `x3` names.

The separate `legal-counted-compact-context/v1` declaration retains the three
sorts, exact `Member : Object × EventFrame × TimeFrame → Bool` signature,
ordered `object,event,time` roles, event/time policy, maximum integer three,
built-in distinctness rule and object variables. It contains no expression,
signature or node ID. It is the same fixed declaration for every accepted
request. A projection labels it **target-derived authored declaration data**;
validation does not establish that it is permitted independent inference
context. No source text, source hash or identity sidecar is an input to content
or token prediction decoding.

`legal-counted-compact-identity/v1` is archival material. It retains complete
original expression/signature IDs, all 49 node IDs in preorder, fixed binder
names, content/context hashes, original expression identity, original raw
request hash and canonical request hash. Arbitrary valid caller IDs survive
reconstruction exactly. The sidecar is never encoded as predicted content.

The APIs are:

- `project_counted_frame_request_v1(request_raw, *, expected_request_sha256)`
  genuinely prepares the original through `prepare_counted_frame`, derives
  content/context/identity and checks a complete archival inverse through a
  second genuine preparation. `roundtrip_receipt` records exact canonical
  request and typed-expression recovery only after that comparison.
- `validate_counted_frame_projection_v1(report, request_raw, *,
  expected_report_sha256, expected_request_sha256)` independently pins the
  whole offered report and fully regenerates it from the original raw request.
- `decode_counted_frame_content_v1(content_raw, context_raw, *,
  expected_content_sha256, expected_context_sha256)` checks the closed grammar,
  generates fresh deterministic IDs and genuinely prepares that complete
  typed frame. It accepts no reference, original request or sidecar.
- `reconstruct_counted_frame_request_v1(content_raw, context_raw, identity_raw,
  original_request_raw, *, expected_content_sha256, expected_context_sha256,
  expected_identity_sha256, expected_original_request_sha256)` checks all
  independent input pins, compares the whole sidecar against the complete
  independently supplied original, restores its identities, genuinely prepares
  both requests and requires exact canonical request/typed-expression equality.

Use the existing `counted_frame_report_sha256` for ordinary complete report,
content, context and sidecar hashes. Raw input pins commit original UTF-8 bytes;
canonical hashes commit compact sorted-key JSON. Exact reconstruction means
canonical request recovery, including original IDs. It does not recover the
original JSON whitespace, indentation or key order. The original raw SHA stays
separate; no raw transport round-trip is claimed.

### Fixed lexical codec

`build_counted_frame_token_codec_v1()` and
`counted_frame_token_codec_sha256(codec)` publish and check one fixed
`legal-counted-compact-token-codec/v1` value without loading syntax operation
owners. Its vocabulary contains PAD/BOS/EOS at IDs 0/1/2, the counted schema
and constructor/sort literals, JSON structural lexemes and integers 0 through
5. It has an explicit **512 total-ID** ceiling, including BOS and EOS. It is a
separate symbolic transport with `numerical_head_compatible: false` and
`checkpoint_compatibility_verified: false`; it cannot be substituted for the
existing byte, normative32 or 537-token codecs.

`encode_counted_frame_tokens_v1(content_raw, context_raw, *,
expected_content_sha256, expected_context_sha256, codec,
expected_codec_sha256)` produces `target_ids` and a genuine typed prediction
receipt. `decode_counted_frame_tokens_v1(generated_ids, context_raw, *,
expected_context_sha256, codec, expected_codec_sha256)` requires the independent
exact codec, one BOS, one terminal EOS, no PAD/interior specials, complete
canonical JSON lexical coverage, the fixed counted grammar and genuine typed
preparation. It accepts no original request or identity sidecar. Malformed,
incomplete, noncanonical, out-of-range, Boolean/float/custom IDs, foreign codec,
altered context, extra JSON fields and overflow inputs raise `ValueError`;
there is no silent truncation, EOS repair or arbitrary-byte acceptance.

These are complete sequence operations. No allowed-prefix API, numerical
generation loop or trained checkpoint migration is supplied. Codec dimensions
do not establish a learned conditioning space, token savings or convergence.

The original request/report bounds remain in force. New ordinary mutable
report, codec and ID-list inputs are bounded and detached; original and
detached forms are fenced before and after genuine replay and final report
serialization. Trusted counted/syntax producer pins remain tied to the same
operation generation. Reports retain all-false authority, integer-zero
training/evaluation-gold masks and explicit checkpoint incompatibility. These
are finite named-source/input custody checks, not an atomic concurrency or
executed-bytecode attestation.

The later source-counted join v2 and unsigned counted-review owner retain their
own qualified generations. A changed counted-owner source pin requires fresh
original-input replay for a new integration report; old reports must not be
reidentified as a current generation. The selected §7214 correspondence remains
a partial counting hypothesis with unresolved statutory meaning, edition,
permission/purpose/anaphora and applicability. This transport does not reopen
signed admission, promote a complete norm or add model, training or Lean work.


## Closed compact round-trip qualification

The [closed owning/actual-source qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-compact-roundtrip-20261022-01/qualification-summary.json) qualified 170 distinct cases: 109 original regressions, 60 new controls and one actual §7214 observer. 169 passing cases from the retained first attempt plus one corrected targeted retry; the original 169/170 attempt is retained. The fixed 28-entry counted vocabulary encodes 291 lexical tokens and 293 total IDs including BOS/EOS. All 49 nodes, six binders, six equality occurrences and ordered declaration roles survive; independently pinned original canonical identities reconstruct exactly. These are mechanical fixed-profile measurements, not a learned token/accuracy or source-only inference result.

The changed counted producer has a separate current report/join/unsigned-review generation. Original source and request bytes, typed expression and all 55 provenance rows remain identical. The 35 obligation payloads remain unresolved; six context IDs persist and 29 derived IDs change with the correspondence hash. Preserve the original809d proposal and104/158 qualifications as their own generations. Legacy Object-only content, token and numerical-head sources remain byte-identical. Original native/storage/source READ closed. No model forward/update, checkpoint compatibility, training/gold, general grammar, prefix-completability, statutory meaning, complete norm, signed admission, convergence or new Lean build is qualified.

## Authored threshold target factory v2

The separate owner `legal_counted_frame_threshold_v2.py` builds a bounded family
of authored labels for explicit maxima `{1, 2, 3}`. It preserves the complete
fixed-three v1 source, acceptance behavior, counted28 codec, checkpoints and
existing qualifications. It introduces no new AST, parser, codec, numerical
kernel or Lean lowering, and does not infer a limit or meaning from legal text.

The four public APIs are:

- `authored_counted_threshold_request_v2(maximum)`.
- `prepare_counted_threshold_v2(request_raw, *, expected_request_sha256)`.
- `counted_threshold_report_sha256(report)`.
- `validate_counted_threshold_v2(report, request_raw, *, expected_request_sha256, expected_report_sha256)`.

The request schema is `legal-counted-frame-threshold-request/v2`. The caller
supplies a plain integer maximum and the exact closed authored declaration,
including its fixed frame, membership roles, distinctness policy and matching
object-variable list. There is **no caller expression or AST intake**. The
factory constructs the expression through existing `syntax_core.ast`
constructors, signatures and `TypedExpression` elaboration, preserving ordered
binders, Member arguments, equality pairs and binary grouping. Built-in equality
is object identity, not an opaque `Eq` predicate or occurrence multiplicity.

| Maximum | Nodes | Quantifiers | Memberships | Equality pairs |
| --- | --- | --- | --- | --- |
| 1 | 17 | 4 | 2 | 1 |
| 2 | 31 | 5 | 3 | 3 |
| 3 | 49 | 6 | 4 | 6 |

All variants quantify `EventFrame`, `TimeFrame` and then their object variables,
with `Member : Object × EventFrame × TimeFrame → Bool`. Each bound applies
independently to the same event/time pair; it is no global or cumulative cap.
Empty membership is allowed and duplicate occurrences of an identical object
do not increase its distinct count. Time remains an arbitrary index without
order, calendar, duration or a supplied statutory interpretation.

Preparation reuses the original fixed-three grouped FOL syntax helper. It
requires two genuine canonical parse rounds, original-to-first,
first-to-second and original-to-second alpha agreement, and stable printed
text. Its report schema is `legal-counted-frame-threshold-report/v2`, profile
`authored-at-most-one-to-three-distinct-per-event-and-time/v2`. Reports retain
the complete original request/raw commitment, typed expression, binder and
node ledgers, counts, canonical FOL, parse receipts and producer commitments.
The validator independently pins the whole offered report, regenerates it from
the complete original request and compares canonical bytes. Resealing an altered
AST, context, schema or authority flag cannot substitute for that replay.
The bounded report hash alone supplies no validation or custody authority.

`signature_context` has schema `legal-counted-frame-signature-context/v2`.
It omits both the cap and cap-derived object-variable list, retaining the same
signature/frame/role declaration for all three targets. This common context
is authored syntactic information whose independent inference permission remains
unreviewed. Its byte equality across labels is not a permission decision or a
source-only context producer. Request maxima, target expressions and binder
counts remain label material.

Finite controls interpret the generated typed AST and compare distinct Member
sets in each frame. Two versus three members distinguish adjacent bounds;
empty relations, duplicate rows and event/time partitioning
exercise the intended declaration. The 16 subsets across three bounds are 48
finite authored checks, not independent laws, source examples or reviewed labels.

Qualification: The [closed qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-threshold-language-20261022-01/qualification-summary-v01.json) passed **67 cases / 201 phases**:57 new threshold controls and10 selected unchanged v1 regressions. Three genuine typed targets have17/31/49 nodes,4/5/6 quantifiers and1/3/6 builtin identity equalities. All48 subset/threshold interpretations agree with independent distinct-object cardinality; additional equality-pair, duplicate and event/time controls distinguish the target semantics. The existing canonical FOL parser/printer and alpha checks preserve all three trees. Their cap-free signature contexts and hashes are identical. Original source/native/storage custody closed. These authored targets supply no legal-text inference, reviewed corpus, codec/token/head compatibility, source-dependent training accuracy, graph admission or new Lean build; masks remain integer0.

This target factory emits no token sequence, allowed-prefix route, decoder,
model result, training example admission, Lean text or build. In particular,
the old fixed-three codec must reject unsupported successor targets rather
than silently expand its language. A varied compact profile and independently
qualified decoder compatibility remain follow-up work. The source binding is
null; review/admission authority remains false and training/evaluation-gold masks
remain integer zero. The §7214 partial hypothesis retains its unresolved source,
edition, counting unit, meaning, definitions, permission, purpose/anaphora and
applicability questions. This authored label family is not complete legal-text
autoformalization or a reviewed statutory training population.


## Three-form threshold codec and prefix v2

The separate `legal_counted_threshold_codec_v2.py` transports exactly the three
authored threshold targets through the existing typed factory. Its profile is
`authored-one-to-three-many-sorted-compact/v2`, with content schema
`legal-counted-threshold-content/v2` and codec schema
`legal-counted-threshold-token-codec/v2`. It preserves the complete fixed-three
v1 owner, threshold-factory v2, singleton prefix inspector, old counted28 codec
and all existing checkpoint identities. Sharing a 28-entry vocabulary width
supplies no checkpoint or numerical-head compatibility.

The five public APIs are:

- `build_counted_threshold_token_codec_v2()`.
- `counted_threshold_token_codec_sha256(codec)`.
- `encode_counted_threshold_tokens_v2(request_raw, *, expected_request_sha256, codec, expected_codec_sha256)`.
- `decode_counted_threshold_tokens_v2(generated_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256)`.
- `inspect_counted_threshold_prefix_v2(prefix_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256)`.

The codec reuses the public fixed-three codec builder, replacing the content
schema spelling and declaring a distinct profile, format, context commitment
and implementation generation. Its 28 distinct spellings include PAD/BOS/EOS;
27 spellings are shared with the old vocabulary and the new content-schema
literal replaces the old one. Token identities must be compared by exact
spelling, since sorting can change numeric row positions. A codec hash accepts
only the exact successor declaration; it is no old-codec alias or validation of
an arbitrary compatible-looking vocabulary.

Encoding accepts the complete independently pinned original threshold
**declaration request**, not a caller AST, expression or legal text. Genuine
`prepare_counted_threshold_v2` constructs the typed expression and performs its
existing FOL print/parse/alpha replay. The unchanged compact tree projector
retains builtin identity, sorted binders, ordered Member roles and binary
connectives. The output contains canonical compact JSON, lexical tokens,
BOS/EOS-framed IDs, common context, counts and the genuine typed prediction.
Original request whitespace remains committed in its prediction; a separate
canonical declaration replay fixes the content identity.

Complete decoding accepts offered IDs and the independently pinned exact
common signature context and codec. It accepts **no reference target, original
request, chosen maximum or expected answer**. It enforces plain in-range IDs,
one initial BOS, one terminal EOS, no interior special token and a complete
512-ID budget. The lexical tokens must reconstruct canonical JSON with exact
lexical segmentation. The offered content must match exactly one of the three
forms prepared by the genuine public threshold factory. The returned candidate
contains that actual typed prediction, its counts and the decoded maximum;
that maximum is output label material. An equivalent-looking arbitrary formula,
changed binder order or unsupported bound is outside this closed language.

Prefix inspection uses the same codec and cap-free context, with zero through
512 bounded plain integer IDs. It considers **every** matching form, returning
`prefix`, `complete` or `rejected`, the union of allowed next IDs, matching
completion count and minimum/maximum IDs still needed across survivors. Empty
input permits BOS. Shared prefixes retain all matching bounds until their
actual token paths diverge. A complete valid EOS has no next ID and calls the
public successor complete decoder; `complete_candidate` retains that genuine
result. Wrong paths, out-of-vocabulary IDs or extra tokens are rejected data,
while malformed containers, bounds and independent commitments refuse. A
finite grammar branch or deterministic completion is no learned decision.

The context is the threshold factory's identical cap-free signature declaration
for all three forms. It omits maximum and cap-derived object-variable lists,
but remains authored syntactic information with unreviewed inference permission.
No reference tree, target-derived binder count or chosen cap is accepted by the
decoder or prefix inspector. This interface boundary does not itself establish
a permitted source-only context producer or source-to-vector correspondence.

Operations retain canonical factory/fixed-owner origins, their source hashes,
the successor's self hash and the existing syntax-owner commitments. Caller
codec/ID lists and generated requests, reports, content, lexemes and IDs are
bounded, detached and fenced across genuine work, capture, serialization and
exceptional closing paths. These are finite named-source/input custody checks;
they do not attest every executed byte or provide atomic concurrency isolation.

Qualification: The [closed qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-threshold-codec-20261022-01/qualification-summary-v01.json) passed **81 cases / 243 phases**: 77 new codec/prefix controls and 4 selected unchanged regressions. The three genuine typed factory targets round-trip as 117/195/293 total IDs including BOS/EOS, retaining 17/31/49 nodes and the identical 483-byte cap-free context. The accepted saved panel records 525 distinct valid prefix states, 14700 independently checked 28-way next-token edges and 2 branching states. All three complete EOS paths invoke genuine public successor decoding; no reference target or chosen cap is passed to prefix inspection or decode. Original source/native/storage custody closed. The old fixed-three codec, singleton prefix inspector and numerical/checkpoint generations remain unchanged. These are finite authored transport/completion measurements, with no model forward/update, legal-text inference, source-dependent accuracy, reviewed statutory gold, graph or new Lean qualification; masks remain integer 0.

All authority flags remain false, training/evaluation-gold masks remain integer
zero and source dependence remains unestablished. This is a finite authored
label transport and prefix route, with no source encoder, numerical forward,
generation loop, trainer, optimizer update, reviewed statutory population,
complete norm, graph admission or Lean text/build. Existing numerical transfer
and singleton losses retain their original codec and source generations. A
varied decoder consumer still needs separately qualified codec/head adaptation,
independently authored prose and permitted source-only context, grouped held-out
source evaluation and reviewed target admission. The unresolved US Code meaning,
edition, counting-unit, definition, purpose/anaphora and applicability questions
remain open.


## Seeded numerical vocabulary view for three forms

The separate numerical owner `legal_counted_threshold_numerical_view_v2.py`
consumes the qualified three-form threshold codec through an explicit view of
unchanged seeded counted28 weights. It preserves all original owners,
checkpoint bytes, tensor states and old codec identities. Its profile is
`seeded-counted28-three-form-vocabulary-view-384/v2`; it creates no new head,
checkpoint, replacement row, optimizer state, trainer or generation loop.

The four APIs build and hash the exact fixed metadata view, score a raw prefix
and evaluate one complete teacher-forced label. Their signatures and numerical
contract are documented in [the existing compact-head guide](legal_compact_content_head_v1.md#seeded-three-form-numerical-vocabulary-view-v2).
The metadata view does not bind or restore a checkpoint. Each scoring/evaluation
operation instead validates the independently pinned original seeded checkpoint
through its existing owner and reports its checkpoint, weights and old model
codec separately from the successor observation codec.

Twenty-seven spellings map exactly. The new content-schema spelling explicitly
uses the old schema spelling's numerical row; that is a declared role relabel,
not a learned replacement or an exact spelling match. Both schema spellings
occupy row 10 and all 28 numeric IDs are identical for these exact codecs. The
adapter therefore demonstrates no nonidentity permutation. It maps offered
successor prefix IDs into model rows and relabels every unmasked old logit into
successor order, without rewriting any checkpoint or tensor. An edited view,
codec or foreign transferred snapshot is refused; transferred weights retain
their separate original-donor-required owner.

Evaluation first calls genuine complete successor decoding for the offered
117/195/293-ID label and the independently pinned common context, with no
reference target or chosen cap. It then observes 116/194/292 unmasked 28-way
teacher-forced positions, including terminal EOS. The old GRU receives the
caller-supplied 384-vector and mapped token prefix only. The common cap-free
signature context remains unreviewed label-validation material and never
enters the vector or forward call. Neither deterministic syntax completion nor
exposed teacher-forced loss establishes source-dependent learning.

Qualification: The [closed qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-threshold-numerical-consumer-20261022-01/qualification-summary-v01.json) passed **46 cases / 138 phases**, all focused numerical-view cases; no legacy whole campaign was rerun. The same unchanged seeded checkpoint supplies three complete 116/194/292-by-28 unmasked teacher-forced observations including EOS. Actual per-form diagnostics: limit 1: CE 3.2715484464624036, 3/116 raw token matches; limit 2: CE 3.2540739577967495, 7/194 raw token matches; limit 3: CE 3.2525432199783406, 11/292 raw token matches. Each principal public evaluation records one strict host restore and one GRU forward; independent host/CE test oracles execute additional calls outside that instrumentation scope. Direct original-host logits match exactly and independent saved-logit cross-entropy agrees. The 13 tensor states, checkpoint/weights identities and CPU RNG are unchanged; 27 spellings match and one row 10 schema marker is explicitly relabeled, with an identity numeric map and no new row, checkpoint, transfer, optimizer, backward/update or generation. Changed fabricated conditioning changes raw scores; these are exposed authored-label diagnostics with no learning gain, source-held-out or statutory accuracy. The 483-byte common context remains unreviewed label validation only. All authority flags remain false and masks integer 0. Original source/native/storage custody closed.

Source/input checks retain the existing owner boundaries, with an additional
check immediately before each actual forward and a closing check after host
result serialization. This is finite named-source/input custody, not a full
bytecode or third-party runtime attestation. Original numerical and semantic
owners retain their own qualified generations. Source/review/proof and
checkpoint-compatibility authority remain false; training/evaluation-gold masks
remain integer zero. No legal-text inference, permitted source-only context,
verified source-to-vector correspondence, reviewed statutory population,
training gain, graph admission or new Lean work is supplied.

Next qualify a target-independent numerical generation consumer separately
from the existing finite prefix grammar, then pair independently authored prose
with permitted source-only context and grouped held-out, constant-label and
shuffled-label controls. Actual law admission still needs independent reviews
of counting units/frames, governing definitions, edition/applicability,
permission, purpose/anaphora and competing interpretations. Three authored
labels and fabricated conditioning do not satisfy those requirements.

## Public symbolic publication closeout, 2026-10-23

**Counted symbolic source publication, 2026-10-23:** [datasets PR #1354](https://github.com/endomorphosis/ipfs_datasets_py/pull/1354) merged as `a70fa3368b1957fff217f5044e8cd15ca80f7a27`; [parent PR #600](https://github.com/endomorphosis/lift_coding/pull/600) adopts it at `b57e413716cb2d2ae61c4c816e6b7badeeaaa45c`. The [closed source-reuse review](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-threshold-publication-20261023-01/source-qualification-reuse-review-v01.json) and [publication closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-counted-threshold-publication-20261023-01/publication-closeout-v01.json) cover only the three existing symbolic owners: fixed-three compact content/identity/lexical transport, authored limits1/2/3 and the finite codec/prefix route. Exact six primary source/test bytes already match; no primary code installation or new tests/native/model/Lean run is performed. The historical170-distinct aggregate retains169 passes plus one corrected targeted retry, including its separate private observer; factory67/201 and codec81/243 remain separate. Source/edition/meaning, governing definition, two distinct uses, permitted context, training/gold, graph and Lean admission remain open. Hosted CI success is not claimed.

