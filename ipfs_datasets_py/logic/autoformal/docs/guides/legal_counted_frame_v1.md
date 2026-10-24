# Authored counted-frame profile v1

**Public delivery boundary:** this guide covers three existing symbolic owners: `legal_counted_frame_v1`, `legal_counted_frame_threshold_v2` and `legal_counted_threshold_codec_v2`. The fixed-three owner preserves its original public source and owning-test prefixes while adding compact content, identity restoration and lexical transport; the two successor owners provide authored limits 1/2/3 and their finite codec/prefix route. This delivery includes no counted source-join or unsigned-review extension, numerical head/transfer/view, source encoder, trainer, learned generation loop or statutory corpus. Those separate primary/historical observations below are provenance, not interfaces supplied by this publication.

The original public profile guide at `docs/autoencoders/legal_counted_frame_v1.md` remains unchanged. Use this canonical guide for the selected symbolic successors and their separate evidence scopes.

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

Separate retained primary/historical source-counted join v2 and unsigned counted-review work uses this fixed-three fragment as an unreviewed proposal. Those extensions are outside this public delivery. The public source-join and relational review contracts are not widened here; use their own published capabilities rather than assuming these historical counted consumers are available.

The retained §7214 proposal and unsigned counted-review packet are historical primary evidence. Their counting unit/frame, permission scope, assignment restriction, purpose, pronoun and entity/definition correspondence still require supported decisions and independent review; §7213 alternatives remain unreviewed. This publication does not replay those operations or supply an accepted complete norm, governing-definition edge, review signature, source-linked lowering, graph/corpus/Lean admission or training/evaluation gold. Masks remain zero.

Historical model experiments retain their original profiles and outcomes. This symbolic publication performs no training, rescoring, source capture or model replay and supplies no learned reconstruction or convergence result.

## Historical recovery and native observations

The original fixed-three owner and tests were recovered from commit `2b9f325a080001272ac6dd3949cff5a4566281eb`. The historical adoption evidence separately records 109 migration controls and one successful actual Lean build after a failed build with incomplete Lake roots. The 109 controls were not rerun; the failed cohort and its original-owner storage closeout remain preserved. Historical 277-case zero-build evidence, the two native build attempts and their source generations remain separate. The three-module publication adds no build or qualification to those histories; the portable evidence record retains their original locators and scope.

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

These fixed-three v1 APIs are complete sequence operations. They supply no
allowed-prefix API, numerical generation loop or trained checkpoint migration;
the separate threshold codec/prefix v2 is described below. Codec dimensions
do not establish a learned conditioning space, token savings or convergence.

The original request/report bounds remain in force. New ordinary mutable
report, codec and ID-list inputs are bounded and detached; original and
detached forms are fenced before and after genuine replay and final report
serialization. Trusted counted/syntax producer pins remain tied to the same
operation generation. Reports retain all-false authority, integer-zero
training/evaluation-gold masks and explicit checkpoint incompatibility. These
are finite named-source/input custody checks, not an atomic concurrency or
executed-bytecode attestation.

Historical primary source-counted join v2 and unsigned counted-review results have their own source-pinned generations and are not included here. A changed counted-owner pin requires an explicitly qualified integration; old reports cannot be relabeled as current. The §7214 interpretation, source edition and definition/use decisions remain unresolved. Symbolic transport supplies no complete norm, signed admission, model, training or Lean result.


## Closed compact round-trip qualification

The [closed owning/actual-source qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-threshold-publication-20261023.json) qualified 170 distinct cases: 109 original regressions, 60 new controls and one actual §7214 observer. 169 passing cases from the retained first attempt plus one corrected targeted retry; the original 169/170 attempt is retained. The fixed 28-entry counted vocabulary encodes 291 lexical tokens and 293 total IDs including BOS/EOS. All 49 nodes, six binders, six equality occurrences and ordered declaration roles survive; independently pinned original canonical identities reconstruct exactly. These are mechanical fixed-profile measurements, not a learned token/accuracy or source-only inference result.

The historical round-trip campaign also retained a separate primary report/join/unsigned-review generation: original source/request bytes, typed expression and 55 provenance rows stayed identical; the 35 obligations remained unresolved, six context IDs persisted and 29 derived IDs changed. These downstream consumers and replay observations are not delivered or rerun here. Preserve the original809d proposal and104/158-case qualifications as separate generations. Legacy Object-only content/token/head identities and original source/native/storage closure retain their historical scope; no model, training/gold, statutory, graph or new Lean qualification follows.

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

Qualification: The [closed qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-threshold-publication-20261023.json) passed **67 cases / 201 phases**:57 new threshold controls and10 selected unchanged v1 regressions. Three genuine typed targets have17/31/49 nodes,4/5/6 quantifiers and1/3/6 builtin identity equalities. All48 subset/threshold interpretations agree with independent distinct-object cardinality; additional equality-pair, duplicate and event/time controls distinguish the target semantics. The existing canonical FOL parser/printer and alpha checks preserve all three trees. Their cap-free signature contexts and hashes are identical. Original source/native/storage custody closed. These authored targets supply no legal-text inference, reviewed corpus, codec/token/head compatibility, source-dependent training accuracy, graph admission or new Lean build; masks remain integer0.

This target factory itself emits no token sequence, prefix route, model result, training admission, Lean text or build. The separately described codec/prefix v2 below supplies the finite symbolic transport for these three targets; numerical head/consumer compatibility remains separate. The fixed-three codec keeps its original closed language. Source binding remains null, authority false and masks integer zero. No source edition, counting unit, meaning, governing definition, permission, purpose/anaphora or applicability decision is supplied by these authored labels.


## Three-form threshold codec and prefix v2

The separate `legal_counted_threshold_codec_v2.py` transports exactly the three
authored threshold targets through the existing typed factory. Its profile is
`authored-one-to-three-many-sorted-compact/v2`, with content schema
`legal-counted-threshold-content/v2` and codec schema
`legal-counted-threshold-token-codec/v2`. It preserves the original fixed-three
v1 interfaces and codec, the threshold-factory v2 contract and existing checkpoint
identities. The separately retained singleton inspector is outside this delivery. Sharing a 28-entry vocabulary width
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

Qualification: The [closed qualification](../../../../../docs/autoformalization/evidence/legal-ir-counted-threshold-publication-20261023.json) passed **81 cases / 243 phases**: 77 new codec/prefix controls and 4 selected unchanged regressions. The three genuine typed factory targets round-trip as 117/195/293 total IDs including BOS/EOS, retaining 17/31/49 nodes and the identical 483-byte cap-free context. The accepted saved panel records 525 distinct valid prefix states, 14700 independently checked 28-way next-token edges and 2 branching states. All three complete EOS paths invoke genuine public successor decoding; no reference target or chosen cap is passed to prefix inspection or decode. Original source/native/storage custody closed. The old fixed-three codec, singleton prefix inspector and numerical/checkpoint generations remain unchanged. These are finite authored transport/completion measurements, with no model forward/update, legal-text inference, source-dependent accuracy, reviewed statutory gold, graph or new Lean qualification; masks remain integer 0.

All authority flags remain false, training/evaluation-gold masks remain integer
zero and source dependence remains unestablished. This is a finite authored
label transport and prefix route, with no source encoder, numerical forward,
generation loop, trainer, optimizer update, reviewed statutory population,
complete norm, graph admission or Lean text/build. Historical numerical transfer
and singleton-loss observations are separate unbundled profiles with their own
codec and source generations. A
varied decoder consumer still needs separately qualified codec/head adaptation,
independently authored prose and permitted source-only context, grouped held-out
source evaluation and reviewed target admission. The unresolved US Code meaning,
edition, counting-unit, definition, purpose/anaphora and applicability questions
remain open.


## Retained §7214 full-sentence proposed compositions

The [preparation record](../../../../../docs/autoformalization/evidence/legal-ir-title10-7214-pending-composition-preparation-20261024.json) and [exact saved data](../../../../../docs/autoformalization/evidence/legal-ir-title10-7214-pending-compositions-20261024.json) extend the retained 2024 paragraph beyond the old cap-only proposal. This is a fixed data preparation through existing `syntax_core` owners, not a new public API, counted profile, decoder target admission or legal interpretation. Start with this summary; load the full generated packet only when working on that target.

The original 49-node counted expression remains intact as provenance. Each draft uses its byte-exact 47-node inner core under shared `event`/`time` binders, retaining the original binder lineage without variable renaming. Two alternative trees express `G → P(Cap ∧ Body)` and `(G ∧ Cap) → P(Body)` at the same frame. Neither is selected or exhaustive.

| Source material | Explicit proposed structure |
| --- | --- |
| President, may, detail | `President(p)`, versioned permission `P`, ordered `Detail(p,o,event,time)` |
| Not more than three officers | Existing four-object identity expansion over `Member(o,event,time)`; no source-verified counting frame |
| Corps assignment | Separate `CorpsEngineers(c)` and `AssignedTo(o,c)` |
| Mayor of the District of Columbia | Separate `DistrictColumbia(dc)` and `MayorOf(m,dc)` |
| Assistance, discharge and his duties | Intended-purpose primitive, existential duties collection and proposed `DutiesOf(d,m)` pronoun relation |

Every source character is retained by the 20-segment literal partition. All 11 lexical features have pending typed links. Each alternative has 98 core AST nodes, one legacy extension payload and 12 binder rows: 111 inventory rows, not 111 AST nodes. All inverse rows are explicit: 16 pending linked rows and 95 introduced, unreviewed scaffolding rows. Geometry and mapping are not semantic completeness.

Important open meaning: the body proposes `Member → Officer ∧ AssignedTo ∧ Detail ∧ Purpose`; it does not state `Detail → Member`. Consequently it does not establish that all detailed officers are covered by the cap. The purpose predicate remains an uninterpreted five-argument relation, not a reviewed decomposition of assistance or duty discharge. Event/time interpretation, office identity/uniqueness and potentially vacuous guards, duties existence, pronoun antecedent and §101 definition applicability remain open. Legal-as-of, source/context/meaning review and governing-use decisions are not supplied. Both alternatives retain null source/admission bindings and zero learning/gold masks.

Five actual data checks passed: retained geometry/origin, genuine typed round-trip and all feature links, two assignment omission refusals, two purpose omission refusals, and pending-authority/source-closure checks. The four omission edits remain valid typed expressions but fail their original source-link inventory; this is an integrity control, not proof that all legal omissions are detected. Four genuine core modules executed under three declared initializer bypasses and one fileless namespace. This is not whole-package, binary or code-object attestation.

The successful original compute/storage claim and both source READs closed. An earlier empty0775directory failed before native admission; its missing normal terminal and separate responsible administrative controller/READ-descriptor closeout remain preserved and unqualified. The success does not reclassify that failure.

No counted owner/parser replay, encoder/model/optimizer operation, signature, semantic graph export or Lean build occurred. The Object-only relational adapter and fixed counted Lean template do not accept the mixed equality/many-sort/modal trees. Reuse the data for substantive review and a separately declared compositional lowering; do not rename an old profile or train on these drafts as gold.
