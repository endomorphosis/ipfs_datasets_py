# Declared historical-parent identity preparation

`ipfs_datasets_py.logic.autoformal.legal_parent_source_identity_bindings_v1`
prepares independently pinned identity declarations over a genuine immutable
`HistoricalParentSourceInventory`. It opens no files, decodes no parent/source
text, chooses no cache occurrence and assigns no groups or splits. Evidence is
immutable-byte custody and scoped declared assertions, not source authentication
or a qualified legal review. All source authority remains false and masks zero.

```python
raw = build_unresolved_parent_source_identity_bindings_v1(inventory)
report = prepare_parent_source_identity_bindings_v1(
    inventory, raw,
    expected_bindings_sha256=sha256_of_exact_raw_bytes,
    evidence_raw_by_sha256={},
    limits=ParentSourceIdentityBindingLimits(),
)
validate_parent_source_identity_bindings_v1(
    report, inventory, raw,
    expected_report_sha256=parent_source_identity_binding_sha256(report),
    expected_bindings_sha256=sha256_of_exact_raw_bytes,
    evidence_raw_by_sha256={},
)
```

Expected hashes are independent caller inputs. The example hash helper is not
itself evidence that a supplied report is valid; the validator fully regenerates
the preparation from the original inventory, declaration bytes and evidence map.

## Versioned JSONL input

`bindings_raw` is immutable canonical UTF-8 JSONL. Each object has sorted keys,
compact separators and exactly one LF. The first line is a closed header:

```json
{"encoding":"canonical-header-and-rows-jsonl/v1","inventory":{"manifest_file_sha256":"…","manifest_canonical_sha256":"…","parent_descriptor_sha256":"…","preflight_report_sha256":"…","row_count":60077},"schema":"legal-parent-source-identity-binding-declarations/v1","unknown_declaration_profile":"null-means-all-unknown/v1"}
```

The inventory hash is the original manifest file hash including LF; its canonical
object hash is separately bound. Every declared header field must exactly match
the genuine loaded inventory. Header equality is canonical-byte equality, so
booleans cannot stand in for integer counts.

Exactly one subsequent line covers each contiguous physical ordinal, in order:

```json
{"parquet_row_index":0,"physical_section_id":"sha256:…","full_raw_row_sha256":"…","source_projection_sha256":"…","status":"unresolved","document":null,"revision_coordinates":null,"cid_referent":null,"evidence_refs":[],"issues":["no_independent_identity_binding_supplied"]}
```

This illustrative object is displayed for its fields; actual wire keys must be
sorted. `source_projection_sha256` hashes the entire original detached inventory
row, without LF. `parent_source_identity_projection_sha256(row)` exposes that
recipe. It binds all physical fields, text statistics/hashes, normalization,
identity observations/status/evidence and source-only flags. The preparation
keeps those original projections in the inventory and commits them by digest;
it does not copy or alter them as identity declarations.

Missing/extra/reordered/duplicate slots, changed physical/raw-row/projection
commitments, trailing records and malformed or noncanonical wire fail the whole
population. Status is one of `unresolved`, `declared_with_evidence`, `conflicting`
or `unsupported_profile`. Issues are sorted unique nonblank strings. An unresolved
slot has null declaration objects, no evidence refs and explicit issues.

## Unknown is not absent

The versioned null profile means **all coordinates unknown**, never absent or
not applicable. It avoids repeating verbose unknown objects for every one of
60,077 rows. A nonnull `document` has exactly these coordinate entries:

`jurisdiction`, `title`, `section`, `kind`, `subsection`, `appendix`, `note`,
`granule`, `edition`, `schedule`, `chapter`.

A nonnull `revision_coordinates` has exactly:

`hub_revision`, `producer_source_revision`, `release_point`, `edition_view`,
`legal_as_of`.

Each entry is `{state, value, evidence_refs}`. `present` has a bounded nonblank
string and supporting receipt refs; `absent` has null plus supporting refs;
`unknown` has null and no supporting refs. Required jurisdiction/title/section/
kind and the inventory-bound Hub revision cannot be absent. A present Hub revision
must equal the original inventory revision. Producer labels, release points,
edition/view and legal-as-of remain separate declared coordinates; none is
expanded from a shortened label or inferred from a citation.

## Evidence receipts and original bytes

`evidence_raw_by_sha256` maps exact raw SHA256 to bounded immutable bytes. All
objects count toward one aggregate bound and are rechecked at closing. A row's
sorted unique `evidence_refs` name canonical assertion receipt bytes, not arbitrary
original bodies. Receipts have this closed profile:

```text
schema: legal-parent-declared-identity-evidence/v1
subject: {inventory_sha256, physical_section_id, full_raw_row_sha256}
assertions: [{field, state, value}, ...]
provenance: {
  declared_by,
  method: declared_identity_assertion/v1,
  originals: [{sha256, bytes}, ...]
}
```

Assertion fields are `document.<coordinate>` or `revision.<coordinate>`; their
states are present/absent. Every original reference must have exact matching raw
bytes in the same evidence map. Originals are opaque and never parsed as legal
truth, source occurrences or review decisions. Receipt subject mismatches, missing
bodies, changed hashes/sizes, unsupported profiles, role cycles and unused evidence
fail closed. Multiple subject-bound receipts can share one original body.

Every known coordinate must have matching nominated support. Conflicting
assertions across **all supplied row receipts**, including receipts outside that
coordinate's nominated subset, remain explicit blockers. A convenient supporting
receipt cannot hide a contrary receipt. No evidence field grants semantic,
source, historical-execution, review or proof authentication.

## Candidate document keys and chapter

A document key is produced only for a `declared_with_evidence` row with all
document/revision states known and supported without conflict. The genuine public
`uscode_identity.LegalIdentity` normalizes the fully declared document coordinates.
Its real import/optional-dependency closure must be qualified by the execution
owner; all-unresolved preparation does not import that canonicalizer.

The existing citation-oriented `legal_id` omits `chapter`. Therefore the new key
hashes the legal ID **and** a versioned full normalized qualifier-state/value
companion including chapter and explicit revision coordinates. It does not change
the existing legal-ID owner. Evidence/receipt hashes, physical subjects and
inventory hashes are excluded from this document-key recipe: two independently
evidenced occurrences with the same declared coordinates get the same engineering
key. Their provenance and physical identities remain distinct. Different chapters
or producer coordinates can differ despite equal citation-oriented legal IDs.

Partial nonnull declarations retain their state/value companion with null legal
ID/key until fully supported. A null declaration remains null under its explicit
all-unknown profile. `cid_referent` must remain null in this narrow version; a
nonnull interpretation is refused. Original CID observations stay opaque in the
unchanged inventory. No CID decoder or alias-selection authority is invented.

## Complete preparation and limits

The report keeps every original ordinal/physical/raw-row/projection commitment,
known exact-text and normalized keys, declaration status, qualifier companion,
evidence refs, issues and blockers. Unknown document/revision coordinates remain
unresolved; missing text adds `exact_text_unavailable` and
`normalized_content_unavailable`. Counts retain the full denominator. The nine
missing-text rows cannot acquire text or normalized hashes from a candidate
lineage declaration, and unknown keys are never unioned or replaced by singleton
or empty-text hashes. The separate 62,931-row release supplies no inherited splits.

`preparation_sha256` hashes the report excluding that field;
`parent_source_identity_binding_sha256(report)` hashes the full report including
it. Validation checks the independently pinned report, regenerates all rows from
original inputs and checks report/input stability. Neither hash alone is proof.
The inventory's ordinary frozen public-API contract is reused; this is not an
isolation boundary against arbitrary reflective Python mutation.

`ParentSourceIdentityBindingLimits` is a genuine frozen lower-only dataclass:
65,536 rows; 64 MiB declarations and preparation; 4 KiB header/declaration/output
row; 8 MiB aggregate evidence; 1 MiB per evidence body; 4,096 evidence objects;
16 refs per row/coordinate/provenance list. Limits must be positive plain integers
and are revalidated before serialization and at closing fences. JSONL is parsed
one bounded line at a time; original bytes are not embedded or escaped into the
output. Preparation hashing reserves JSON punctuation, escapes and UTF-8 bytes
before streaming encoder chunks, with a separate four-million-node bound.

Fixed unresolved construction uses at most 768 bytes per row plus 1,024 header
bytes: 50,332,672 bytes at the 65,536-row ceiling. A conservative independent
output template with maximal ordinals, both full text hashes and all four blockers
has 896 canonical bytes/44 nodes per row; including top-level allowance, the
65,536-row output is below 59 MiB and 2.9 million nodes. The actual admitted case
must measure its own declaration/preparation bytes and worker RSS. These are
representation arithmetic bounds, not a resident-memory or throughput claim.

Even every declared document key becoming available would not establish source
truth, recover text, select original producer occurrences or close legal
definition/exception/context/time dependencies. Source and meaning review,
scientific training eligibility, partitions, Lean admission, convergence and
publication remain separate gates. This interface grants none of them.
