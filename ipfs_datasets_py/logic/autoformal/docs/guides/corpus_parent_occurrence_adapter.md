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
