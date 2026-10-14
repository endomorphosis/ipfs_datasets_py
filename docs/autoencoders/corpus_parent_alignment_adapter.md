# Complete parent and official alignment corpus supplement

`corpus_parent_alignment_adapter` transports the complete output of the existing
`legal_parent_source_alignment` owner into bounded candidate corpus records. It
replays the original parent/cache/sentence owners and the alignment owner before
projection. It adds no matcher, semantic extractor, reviewer or Lean compiler.

The base occurrence corpus remains external and unchanged. Its original manifest
JSON and complete record JSONL each require independent raw SHA256 pins. The
three original parent/cache/sentence reports require independent raw and FULL
canonical hashes, together with the complete seven-field fixed-owner replay.
The alignment report requires a separate raw and FULL canonical hash. FULL owner
hashes include internal seals; an internal pre-seal digest is not a FULL pin.

The public interface is:

```python
build_parent_alignment_corpus(
    *, base_corpus_bytes, expected_base_corpus_pins,
    base_report_bytes, expected_base_report_pins, base_replay_inputs,
    alignment_report_bytes, expected_alignment_report_pins,
    document_inputs, expected_document_population_sha256,
    limits=None,
)
validate_parent_alignment_corpus(bundle, **the_same_independent_inputs)
```

`base_corpus_bytes` has exactly `manifest` and `records`, containing immutable
JSON and newline-terminated JSONL bytes. `expected_base_corpus_pins` has the same
two keys, each holding an independent raw SHA256 string. Base reports and replay
use the unchanged occurrence adapter interface. Alignment pins have exactly
`raw_sha256` and `canonical_sha256`. Each of the complete ordered document inputs
has the existing seven-field descriptor/raw/FULL-view-report shape, including
explicit missing raw bodies. There are no caller loaders or replay callbacks.

All supplied raw report, corpus and HTML pins pass before parsing original JSON
or importing operation owners. Complete ordinary nested replay inputs are
preflighted with the existing exact UTF8/escaped-JSON byte counter and remaining
aggregate budget. Duplicate JSON keys, non-finite numbers, unbound populations
and raised limits are refused. Repository producer source hashes are checked
before and after original replay, projection, final manifest sealing and final
validation. These checks do not authenticate installed distributions, historical
model operations, continuous process custody or an absolute memory quota.

The returned object has exactly `manifest`, `pages` and `records`. The records
contain only new supplement records. The root binds the exact base transport
bytes and base manifest CID, original alignment bytes/FULL hash, complete replay
and ordered page references. Each page contains ordered entries with global
ordinal, record CID, whole sealed-record SHA256 and population kind. Root page
references bind the page CID/hash, page/global ordinals, record count and first
and last record CIDs. Validation refuses omitted, extra, reordered, duplicated
or resealed records/pages through complete independent source regeneration.

Every root, page and individual record retains the common 1 MiB envelope. Pages
contain at most 256 records by default and split deterministically when a lower
page-byte cap requires it. Separate lower-only limits bound the full collection
at 64 MiB, 32,768 new records and 256 pages; the original alignment report at
16 MiB; base manifest at 1 MiB; base records/replay objects at 16 MiB; and complete
input transport/replay bodies at 64 MiB. Existing source-owner population limits
also apply. Larger populations require a separately qualified profile rather
than truncation or increased common envelopes. Public import is inert; original
Parquet/HTML operation owners load only for explicit build or validation.

Physical source records reuse the existing `corpus_source` schemas. Parent
versions and matching occurrences/contexts reuse their exact base CIDs. New
parent geometry retains the same immutable file/revision/full-row/ordinal/field
identity. Cache aliases and local custody paths do not enter core identity.

Official normalized-v2 and data-event-rendered views receive distinct source
versions, even when literal strings coincide. Both bind verified supplied raw
HTML bytes, while their selectors address their separate extracted text origins.
Normalized identity retains the declared normalized-view identity, including
decoder/heading/normalization labels. Rendered identity retains decoder, rendering
and coordinate-origin declarations. Edition and legal-ID values are comparison
source declarations; they do not establish governing applicability or a parent
edition. Distinct acquisitions of identical immutable source/view content reuse
core source versions while preserving separate document and observation records.

One observation record survives for every supplied document, comparison, block,
anchor, parent partition piece, official partition piece, render event and render
fragment. Nonempty occurrences share IDs only within the same physical source
version and exact character/UTF8 range. Evidence membership remains separate.
Original JSON pointers bind complete original values and their canonical hashes;
unknown source metadata and complete source texts remain in the externally pinned
full originals. Alignment records bind both parent and official occurrences and
their separately required-unavailable contexts. Partition records bind every
covering alignment record or retain explicit uncovered geometry.

Render event hashes describe parser data before stripping. Events have no raw
HTML occurrence or offset claim and retain nullable fragment links. Fragment
occurrences address the declared stripped/joined rendering. Derived one-ASCII-
space gaps bind the actual whole rendered-field pointer and adjacent original
fragment records; no nonexistent original `gaps` table is invented. Together,
fragments and gaps reconstruct the complete rendered field exactly.

The original-data replay preserves six parents and ten documents, yielding:

| Population | Records or observations |
| --- | ---: |
| New supplement records | 24,699 |
| Inventory pages | 97 |
| Official/rendered source versions | 20 |
| New physical occurrences and required-unavailable contexts, each | 5,854 |
| Complete parent/document comparisons | 60 |
| Literal alignment bindings | 850 |
| Original normalized blocks | 1,476 |
| Parent/official partition memberships | 1,692 / 1,569 |
| Render events / fragments / derived spaces | 3,628 / 1,848 / 1,838 |

Among the anchor bindings, 222 reuse 54 distinct baseline parent geometries;
628 refer to 168 distinct parent geometries absent from the baseline. These
classifications use a baseline snapshot before any supplement range is created.
The complete partition inventory adds another 253 distinct parent ranges,
bringing all new parent ranges to 421. Official normalized and rendered origins
add 1,747 and 3,686 distinct physical ranges. These counts are separate from
binding memberships and from source or legal review.

The full bundle is 51,772,019 canonical bytes. Its root is 47,445 bytes; its
largest page is 51,683 bytes and largest record is 174,847 bytes. All 4,941 base
record bytes are preserved. Actual build and full validation reproduce the
complete supplied original populations; fixture qualification and independent
readback receipts bind the exact implemented source separately.

Every supplement evidence/root/page stays candidate-only. Context records retain
six required-unavailable slots and declaration-only dependencies. Governing
source, legal region, source correspondence, original HTML coordinates,
historical producer operation, reviewed context, training gold, accepted graph
and proof authority remain unverified. The existing 418 pending source-review
requests need a compatible authenticated review profile and actual reviews
before admitting semantic term/entity/definition graphs or Lean4 statements.
