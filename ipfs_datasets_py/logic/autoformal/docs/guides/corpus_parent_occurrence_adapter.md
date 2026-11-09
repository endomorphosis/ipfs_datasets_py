# Corpus identities for literal parent occurrences

`logic.autoformal.corpus_parent_occurrence_adapter` connects the existing
parent-text, cache-occurrence and sentence-candidate owners to the corpus
source-record owner. It preserves their candidate observations and unresolved
statuses; it does not choose a historical span or infer a statutory meaning.

The adapter uses exact decoded Parquet `text` fields. Character offsets count
Unicode code points, byte offsets address the UTF8 encoding of the same field,
and both ranges are half-open. There is no whitespace, Unicode, case or heading
normalization. These offsets do not address original HTML or Parquet file bytes.
The HTML-based statutory-context and native definition-review profiles require
separately verified view correspondence before using these occurrences.

## Independent inputs and replay

`build_parent_occurrence_corpus` takes `report_bytes`, `expected_report_pins` and
`replay_inputs`. The three original report kinds are `parent_text_views`,
`cache_parent_occurrences` and `parent_sentence_candidates`. Each is supplied as
exact immutable JSON bytes with independently retained `raw_sha256` and
`canonical_sha256` pins. The full canonical owner hash includes its internal
seal; it is distinct from both the internal pre-seal digest and the original
file-byte hash. Original serialization remains independently addressable.

The fixed upstream owners regenerate the complete reports from independently
qualified, pinned provenance, producer lineage, page-qualified selected rows,
parent files and view inputs. The supplied provenance classifications remain
trusted prior evidence; this replay does not requalify their authored catalog
AST or attest a historical model invocation. Changing a report and repairing
its seal does not replace that
replay. Caller-supplied parsers, readers or validation callbacks cannot substitute
for the existing owners. Public import is inert; operation owners load when
building or validating the collection.

Every physical cache row and supplied parent comparison remains, including zero
matches, unsupported or unavailable views, incorrect legacy hash declarations
and repeated raw presentations. Literal legal-ID agreement is an observation,
and does not filter matches. Locally verified producer-parent declarations stay
separate from all-parent lexical comparison candidates.

## Identities and complete transport

Source versions reuse `corpus_source` with the exact field bytes as a `text/plain`
artifact and identity normalization. Their source address retains immutable
repository/revision/file/row/complete-row/field provenance. A local file path is
custody metadata rather than the portable physical occurrence identity. Edition
and governing source roles remain unverified; literal metadata stays available
in the original evidence.

The same physical source range has one core occurrence identity. Separate cache
binding records retain each cache identity, physical row, original record/hash
and report pointer. Two cache rows reaching the same range therefore keep both
bindings. Repeated text at another offset or in another physical parent remains
a different occurrence. Historical aliases remain unresolved declarations.

Sentence proposals retain whitespace gaps, unclassified fragments and every
original character in order. Boundary observations, note/heading markers,
dependency mentions and bounded source-local windows stay proposal evidence.
Their presence does not establish legal sentence boundaries, operative regions,
resolved definitions or governing context. Context declarations retain the
existing missing dependency requirements explicitly.

The result is a detached collection of individually bounded corpus records and
a sealed manifest binding their complete ordered population. Its `record_refs`
list retains each complete record's CID and canonical SHA256 in order. Separate
population lists retain parents, cache rows, match bindings and each source-role
kind. The common one-MiB
corpus-envelope limit remains unchanged. Complete original reports are retained
separately under raw artifact identities and full canonical report pins; their
JSON pointers preserve the original evidence without copying a large report
into one envelope. Aggregate bounds apply to the complete operation. An overflow
refuses the collection rather than selecting smaller pieces or dropping rows.
Limits may only be lowered: eight MiB per original report, sixteen MiB for
replay inputs, thirty-two MiB for all input bytes, 8,192 records and sixteen MiB
for the detached collection including its manifest. Existing owner limits may
refuse inputs earlier. Exact JSON byte accounting includes Unicode, escaped
controls, keys and syntax before bulk serialization; replay inputs also respect
the remaining aggregate input budget. These are input/serialization bounds rather than absolute
process-memory or cryptographic-distribution guarantees.

`validate_parent_occurrence_corpus` takes the original independent inputs again,
regenerates the collection and compares its complete ordered contents. Individual
record seals and a repaired manifest alone cannot establish correct membership.
Producer source bindings retain the adapter, corpus and selected fixed replay
owners, including the profile declarations consumed by provenance projection.

## Review and admission

The retained twenty-row/six-parent example has 120 comparisons and 96 unselected
literal matches. Its six parent strings contain 20,230 characters. The sentence
inventory preserves them in 280 pieces, including 137 whitespace gaps, with 534
punctuation observations and 128 unresolved surface reference mentions. This is
a different population from the earlier eight-row, 97-candidate legacy join.

The real fixed-owner replay produces 4,941 records: six source versions, six
parent wrappers, twenty cache-row wrappers, ninety-six cache-match bindings,
1,633 shared physical occurrences, 1,633 required-unavailable context records
and 1,547 role records. Those roles preserve six unclassified regions, fifty-one
markers, all 280 partition pieces, 128 dependency mentions, 534 punctuation
observations and 274 prefix/suffix windows each. Empty windows stay null in the
original segment evidence. The JSONL transport exceeds one MiB while its root
manifest and every individual record retain the original envelope limit.
The final manifest is 881,946 bytes, the largest record 6,210 bytes and complete
JSONL transport 6,013,603 bytes. Adding the used profile-owner source pin and
early byte-budget guards preserves every one of the 4,941 record byte bodies;
the source-bound root manifest changes accordingly. All 84 final adapter tests
pass. These counts qualify this bounded example rather than the whole source
file or span cache.

These records remain candidates. Source authenticity, original producer mapping,
governing edition/region/context, independently reviewed meaning, accepted graph
eligibility, training qualification and Lean admission remain false. Legacy
`admitted` or `formalized` booleans are retained observations with no authority
in this profile. The adapter performs no model inference, training or Lean build.

Next, establish original-source/official-view correspondence, review source
regions and context, and bind explicit definition/entity interpretations through
their existing owners before semantic graph aggregation or Lean compilation.


## Explicit complete-parent capacity

`source_profile="complete-parent-128k/v1"` opts into a maximum of 131,072
characters per complete decoded parent field. Omit it or pass `None` to keep
the legacy 65,536-character behavior and report shape. This changes only parent
capacity: cached diagnostic text still has its original 65,536-character cap
(or a lower caller limit). Aggregate source characters, report bytes, record
counts, detached collection size and common corpus-envelope limits are unchanged.
Every overflow refuses the complete operation; no source substring is substituted.

Pass the same explicit selector to `prepare_cache_parent_occurrences` and
`prepare_parent_sentence_candidates`, and retain it as the optional eighth
`source_profile` field of the complete `replay_inputs` supplied to
`build_parent_occurrence_corpus` and its validator. Validators require the
caller-selected profile and regenerate the original reports. They do not infer
permission from a supplied report or repaired seal. The selected profile is
committed in both reports, replay inputs and the distinct manifest profile
`exact-decoded-parent-field-candidate-records-complete-parent-128k/v1`.

The [focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/qualification-summary-profile-v01.json) passed 19 authored cases / 57
phases (16 new controls and three retained regressions) through the unchanged
original scoped validation worker. It covers exact size boundaries, Unicode
coordinates, complete-field preservation, unchanged cached-text limits and
profile-transplant refusals. It uses a 197-file pinned source closure and explicit
namespace parents with eight initializer bypasses; it does not qualify ordinary
whole-package startup or third-party native kernel internals.

The actual retained section101 row has 71,688 characters / 72,690 UTF8 bytes.
Its full 45-column capture and both existing unreviewed officer-definition
alternatives are pinned in the [retained-input design](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/review/retained-input-design-v01.json). The subsequent actual observation below measured complete upstream reports
and a bank-construction refusal. No actual bank or parent-bound definition
endpoint has qualified; retain the new original reports before the next repair.
The original 837-record section7346 bank and its graph/corpus observations keep
their frozen producer generations. Fresh consumers must replay original inputs
under their selected generation; source hash changes do not transfer old credit.
No governing edition, meaning, definition applicability, training eligibility
or Lean admission is selected by this profile.


## Actual section101 capacity observation

The [closed actual observation](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/actual-parent-bank-v01/request-v02/observation-summary-v01.json) uses the whole physical row39,
all45 raw columns and all16 retained cache rows under the existing128k profile.
No parent substring, source normalization, legal-ID filter or reduced cache
population was substituted. Whole reports passed original validation: parent
views331,168bytes, cache occurrences2,446,615bytes and sentence candidates
4,153,903bytes. The complete replay originals and checked source buffers are
retained beside the reports.

Bank construction returned `CorpusContractError: record exceeds byte bound`
under the unchanged common1MiB sealed-record cap. All three reports fit; no
bank was returned or validated, so no bank CID, record count or parent-bound
definition endpoint is admitted. The saved exception identifies the build
phase, not the oversized record schema or stack frame. Attribute only the
observed common-record frontier. Inspect that record before choosing a repair.
If the root inventory is responsible, reuse the existing bounded inventory
paging algorithm in `corpus_parent_alignment_adapter` within the existing
parent occurrence adapter, with an explicit representation profile and full
ordered replay/refusal controls. Keep legacy shapes and all finite caps.

The original source/native/storage owners closed;14 complete readonly data
files were stream-hashed under opening and closing fences. The initial request
failed before admission because an extra metadata field violated the original
closed schema. Its empty attempt and administrative metadata-wrapper stop are
retained separately, with zero qualification credit. The corrected controller
checks the original owner's exact request fields before launch and commits its
manifest through checked argv/source pins. No service restart or resource
limit increase was required.

Both officer-definition alternatives remain unsigned and unselected. Governing
edition, accepted meaning, per-use applicability, training/gold eligibility and
Lean admission remain unresolved. Historical837/G/E generations are unchanged.


## Explicit inventory paging

Set `replay_inputs["inventory_profile"] = "ordered-record-refs-pages/v1"`
to select the bounded paged inventory in the existing parent occurrence adapter.
This selector controls bank representation only. Keep the independent
`source_profile="complete-parent-128k/v1"` when that complete-parent source
capacity is required; it still selects the existing cache/sentence producers.
Do not pass inventory_profile to those report producers. The combined replay
has nine fields, preserves all original report bytes and selects the distinct
`exact-decoded-parent-field-candidate-records-complete-parent-128k-paged-inventory/v1`
manifest profile. Omitting inventory_profile or supplying None keeps the legacy
inline record_refs shape and identical bytes within the same producer generation.

The bundle keeps its manifest and records keys. Ordinary sealed inventory pages
follow every leaf record inside records; root page_refs bind their complete
hashes, ordinal ranges, counts and first/last CIDs. Each page holds at most256
ordered references and remains under the common1MiB record cap. Pages consume
the existing8192 total-record and16MiB detached-collection budgets. Original
populations and leaf record bodies are unchanged within the selected generation.
Validation checks all ordered leaf/page/root membership and hashes, then rebuilds
from the complete original independently pinned reports and replay inputs. A
caller-selected profile is required; an offered manifest cannot grant permission.

The [focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/actual-parent-bank-v01/paged-inventory-v01/qualification-summary-v01.json) passed40cases/120phases:21new paging
controls and all19 retained size/source/graph regressions, under the original
197-file scoped worker. It covers exact256/257 page boundaries, Unicode and
physical-row separation, a genuine downstream binder, resealed missing/reordered/
forged references, denied selector transplantation and complete lowered-budget
refusals. The14 namespace containers and8 initializer bypasses remain explicit;
ordinary whole-package startup and native third-party internals are unqualified.

The adapter commits its own source pin. This source change therefore creates a
new producer generation and new bank CIDs even for legacy layout; no historical
837-record or graph/corpus qualification is transferred. Direct definition and
context consumers forward the nested replay selector without a new public API.
Legacy alignment/source-review preflights retaining an exact seven-key replay
contract remain separate and are not widened by this change.

The retained actual section101 upstream reports fit their existing bounds, but
the subsequent actual bank observation below closes the bank replay under this
producer generation. Retain all three original reports and the explicit
nine-field replay before preparing both unselected officer-definition alternatives.
Governing edition, accepted meaning, per-use applicability, training/gold
eligibility and Lean admission remain unresolved; all masks stay zero.


## Actual section101 paged bank

The [closed actual bank qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/actual-parent-bank-v01/paged-inventory-v01/actual-bank-v01/qualification-summary-v01.json) builds and validates
the complete physical row39 source field:45 raw columns,71,688 Unicode
characters/72,690 UTF8bytes and all16 retained cache rows. Its fresh bank has
7,347 records:7,318 leaves and29 ordered sealed inventory pages. The full
bundle is11,090,042bytes; every record and the root remain under1MiB, pages
hold at most256 references, and the original8192-record/16MiB collection
limits remain unchanged. The three prior report files were reused unchanged;
only the independently selected ninth inventory-profile replay field was added.

Two witnessed public calls perform genuine complete build and validation,
including internal original-report regeneration. No extra upstream preparation
campaign or law-table census ran. The independent metadata audit verifies all
record CID seals, page membership/order/hashes, population references, exact
character/UTF8 geometry and unavailable-context links. All18 readonly inputs
(435,972,212bytes) have opening/closing complete worker hash fences, with
original source/native/storage custody closed. Private observer-only schema
fixes and their failed metadata receipts remain separate; no native bank retry
was needed after the successful paged operation.

This is a candidate source bank. Its one conservative partition and source-role
observations supply no accepted operative-law classification, governing edition,
meaning, definition applicability or semantic graph/Lean admission. Both existing
officer-definition alternatives have now completed the separate preparation
observation below; legal review and governing applicability remain unresolved. All masks stay
zero. Earlier837/G/E and first common-record refusal retain their original
generations; no old CID or qualification has been relabeled.


## Actual unreviewed officer-definition endpoints

The [closed endpoint qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/source101-parent-definition-v01/actual-parent-bank-v01/paged-inventory-v01/officer-definitions-v01/qualification-summary-v01.json) reuses the complete row39
paged bank and both original competing FOL declarations. Ten witnessed public
entries bind the whole original field and an explicitly unresolved scope, then
prepare, validate, adapt and validate each alternative independently. All
original parent reports and the nine-field replay remain required. No source
substring or old837/section7346 nomination replaces the selected physical row.

| Existing alternative | Body form | Candidate graph nodes | Edges |
| --- | --- | ---: | ---: |
| A | atom | 15 | 23 |
| B | any | 16 | 25 |

Each graph is sealed, distinct and unreviewed, with no APPLIES_WITHIN edge. The
63-character numbered officer unit, seven-character head, five-character means
cue and14-character scope hint retain exact character/UTF8 coordinates. The
actual103-character heading/scope opener and official102-character opener
remain different; the77-character body was not substituted for the complete
opener. Official2024 view/unit references stay historical provenance rather
than parent-governing inputs. Scope labels use the supported unresolved value;
source edition stays not_declared_in_source_artifact and external governing
edition/asof/meaning/per-use applicability decisions remain null. All training,
evaluation-gold, semantic and consumer masks remain zero.

The new actual operation uses canonical source paths and the existing scoped
197-file layout/14declared namespaces/8initializer-bypass policy. It executed
96 checked source files, all17 required production sources and four actual
namespace containers; no old32test-source requirement,40-case qualification or
whole-package startup claim is transferred. No pytest, model, training or Lean
process ran. All21 readonly inputs (448,372,127bytes), recorded return/file
custody and original source/native/storage owners closed.

Reuse the existing [source bridge](../../legal_source_definition_bridge_v2.py)
(`prepare_parent_definition_v1`/`validate_parent_definition_v1`) and
[corpus adapter](../../corpus_definition_adapter_v2.py)
(`adapt_parent_definition_only_bytes_v1`/its validator). The catalog now indexes
these existing owners once; this observation adds no duplicate implementation.
Preparation and authenticated/legal review remain separate qualifications.

Two earlier pre-admission wrappers failed before native ownership (closed-field
and named-root mismatches) and retained source READs without a terminal. Their
failed inputs, empty attempts and separate birth-bound administrative closeouts
are retained with zero qualification credit. The current frontend checks the
original17-field schema, all four physical named roots, ledger schema/capacity
and the unchanged scheduler proof policy before Popen, using the original16MiB
ledger bound. Existing peer successor controls retain their own repair path; a
new original-runner preconstructor terminal requires separate source-generation
qualification rather than an invented cleanup receipt or silent hash refresh.
