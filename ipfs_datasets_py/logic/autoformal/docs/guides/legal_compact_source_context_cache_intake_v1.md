# Selected paired-cache records and declared context associations

`ipfs_datasets_py.logic.autoformal.legal_compact_source_context_cache_intake_v1`
connects complete selected paired-cache record populations to an original-bound
source/context inventory. It reuses the existing paired manifest and payload
owners, retaining every declared physical row slot and every explicit association.
It does not search for a matching legal ID or text, select an original statutory
occurrence, construct a vocabulary from cached answers, or grant inference access.

This guide specifies the API contract. Execution results belong to separate
qualification receipts. Earlier cache, lexical and source/context qualifications
remain dependencies; their cases are not additional tests of this companion.

## Public APIs

```python
prepare_source_context_cache_intake_v1(
    cache_request_raw, cache_bindings_raw,
    *, expected_cache_request_sha256, expected_cache_bindings_sha256,
    manifest_bytes, repository_root, inventory_report, inventory_originals,
)

source_context_cache_intake_sha256(report)

validate_source_context_cache_intake_v1(
    report, cache_request_raw, cache_bindings_raw,
    *, expected_report_sha256, expected_cache_request_sha256,
    expected_cache_bindings_sha256, manifest_bytes, repository_root,
    inventory_report, inventory_originals,
)
```

The hash helper computes bounded whole-report canonical JSON identity without
reading offered cache paths. It does not validate the report or grant authority.
Validation requires an independent expected report hash and all the same
originals. It regenerates the full report and checks the original mutable report
again. Rehashing a changed output cannot replace original-bound replay.

The companion's refusals raise `SourceContextCacheIntakeError`, a `ValueError`
subclass. Existing owner exceptions retain their public types. Known paired
integrity/Arrow decoding refusals become whole-bundle dispositions with all
declared slots retained. Arbitrary exceptions, interruption, import failures and
producer/custody changes are not converted into successful partial intake.

## Independent cache originals

`cache_request_raw` is exact bytes in the unchanged
`legal-paired-manifest-inventory-request/v1` schema:

```json
{
  "schema": "legal-paired-manifest-inventory-request/v1",
  "repository_id": "justicedao/uscode-autoformal-span-cache",
  "revision": "immutable lowercase forty-hex commit",
  "selection_scope": "explicit_paired_manifest_selection",
  "manifests": [{"path_in_repo": "exact existing paired-v1/v2 manifest path", "bytes": 2118, "sha256": "independent raw manifest SHA256"}]
}
```

Actual paths and hashes replace these placeholders. `manifest_bytes` is an exact
plain dictionary mapping every selected manifest path to its original immutable
`bytes`. The existing manifest owner validates those bytes, content fingerprints,
repository/path bindings and complete table descriptors. Keeping these originals
separate from runtime files preserves the declared denominator even if a retained
manifest or table file is missing or corrupt. Missing original manifest bytes or
invalid manifest metadata refuse the request; they cannot invent a row count.

`repository_root` is an existing unaliased absolute local directory containing
the exact repository layout. Local bytes must match the pinned descriptors.
This API performs no download or Hub revision resolution. A directory name or
caller-declared commit does not authenticate a remote acquisition or latest main.
Saved acquisition evidence remains a separate independently pinned artifact.

`cache_bindings_raw` is a second independent original:

```json
{
  "schema": "legal-compact-source-context-cache-bindings/v1",
  "cache_request_sha256": "raw request SHA256",
  "inventory_report_sha256": "complete original inventory report SHA256",
  "rows": [{
    "manifest_path_in_repo": "selected manifest path",
    "row_ordinal": 0,
    "row_sha256": null,
    "occurrence_ids": []
  }]
}
```

Rows follow selected manifest order, then every physical paired-row ordinal from
zero through its declared count minus one. Missing, duplicate, reordered, orphan
or malformed slots refuse intake. Each `occurrence_ids` list contains zero or
more distinct IDs from the original inventory. No text, citation or span ID is
used to fill an absent list.

`row_sha256` is null or an independently expected derived-row hash. When present
and the row can be read, it must match the existing payload owner's exact
serialization. A null expected row hash does not erase the pinned table identity
and physical ordinal. If the bundle cannot be consumed, the actual row and record
hashes remain null; any supplied expected hash is preserved without claiming
that it was verified. The companion never creates a placeholder decoded row.

## Replay the original source/context inventory

`inventory_report` is a complete existing
`legal-compact-source-context-inventory/v1` report. `inventory_originals` is a
plain dictionary with exactly these existing validator arguments:

- `population_raw`, `occurrences_raw`, `catalog_raw`, `access_raw`;
- `expected_population_sha256`, `expected_occurrences_sha256`,
  `expected_catalog_sha256`, `expected_access_sha256`;
- exact typed `source_partitions`, `expected_source_partitions_sha256`;
- `source_resolver` and `expected_report_sha256`.

The existing public validator replays the four originals, physical source
requests, full typed partition inventory including excluded connectors, lexical
catalog and declared access. The new report embeds its fresh result unchanged.
Cache formal outputs, vectors, goals and artifacts never enter those arguments
or become new context symbols, roles or model inputs.

Cache request/binding raw pins and manifest metadata are checked before paired
payload decoding. The pinned inventory report, complete ordered slot declarations
and known IDs are checked before the inventory's source resolver is called.
Raw inventory/source pins retain their existing validation behavior. Source
files, partition witnesses, mutable original arguments, report bytes, manifest
mapping and retained-file identities are checked around the operation. A caller
replacing every original artifact and expected pin supplies a different operation
that a consistency API cannot distinguish from separately authorized work.

## Existing payload owner and physical identity

The companion invokes `legal_paired_payload_intake_v1.prepare_paired_payload_intake`
with `source_bindings=None`. That public owner delegates transport verification
to `span_cache_feed.load_paired_payload` and existing paired-census codecs. It
verifies the whole selected bundle, including all three tables and referenced
artifact evidence, and retains per-row corpus-adapter refusals. No alternate
Parquet decoder, record migration, feed database or source-binding heuristic is
introduced. The complete returned payload report remains embedded unchanged.

Every record retains repository, cache commit, manifest identity, exact paired
table descriptor, physical row ordinal, observation ID and derived row bytes/hash.
`derived_row_json` is the existing owner's sorted-key ASCII JSON serialization
of decoded Parquet values. It preserves strings such as `payload_json` as strings,
including their internal whitespace. It is not the original producer JSON text
or the physical Parquet encoding. The pinned whole-table bytes remain separate.

`physical_record_id` commits to repository, cache revision, paired table path,
table SHA256 and row ordinal. `reference_id` additionally commits to the referring
manifest path/hash. `record_sha256` additionally binds the actual derived-row
hash and is null when no row was read. Repeated logical span IDs, equal text and
competing formal outputs never merge distinct physical rows. Multiple manifests
may refer to the same physical table: each reference and row slot is retained,
with distinct reference identity and explicit physical deduplication counts.

`file_observations` retains expected descriptors, observed size/hash, stable
filesystem witnesses and missing/corrupt dispositions. This binds unavailable
or corrupt inputs without presenting them as verified rows. Oversized files are
not hash-read beyond the declared finite file ceiling; their observed hash is
explicitly null.

## Complete failure and association dispositions

Every manifest has a bundle status, and every declared slot retains that status:

| Record status | Meaning |
| --- | --- |
| `verified` | Existing public paired owner verified and returned the complete row population |
| `bundle_unavailable` | One or more exact runtime bundle files are missing |
| `bundle_corrupt` | A present runtime file differs from its pinned size or SHA256 |
| `bundle_unsupported` | The known paired/Arrow owner refused an otherwise byte-verified bundle's supported format or integrity checks |

An unavailable, corrupt or unsupported bundle retains all manifest-declared
paired slots, with null actual hashes, source observation and derived-row bytes.
Declared expected row hashes and explicit association IDs remain visible.
Unknown/malformed manifest metadata or changing input witnesses refuse the
operation rather than fabricate a denominator.

For readable records, an explicit association compares the cache's nested source
text and text hash with the selected inventory row's exact source input. This is
**source-text association consistency only**. Cache acquisition revision, nested
source revision and physical inventory release remain distinct original fields.
No normalization, legal-ID aliasing or automatic source-occurrence search is used.

| Association status | Meaning |
| --- | --- |
| `unresolved_source_occurrence` | No explicit association was supplied, even if text happens to match |
| `declared_single_association` | One explicit inventory ID has exact text/hash consistency |
| `ambiguous_source_occurrences` | Multiple explicit inventory IDs are text/hash consistent; no preferred origin is chosen |
| `association_source_mismatch` | At least one explicit association differs in text/hash; the record and all outcomes remain retained |
| `cache_record_unavailable` | No decoded row exists for comparison |

Every association preserves the full inventory physical row/input identity and
its existing source-byte verification status. `source_correspondence_verified`
is always false. Equal text plus a declared physical ID does not authenticate
which statutory occurrence, edition or original producer input generated a cache
record. A same-text physical-origin declaration cannot be independently proved
by this API.

The separate `occurrences` table retains every original inventory occurrence in
order. It lists all explicit cache references and, separately, byte-consistent
references. `associated_inventory_occurrences` counts explicit declarations;
`byte_consistent_inventory_occurrences` counts the narrower observed agreement.
Neither is an inference-permission or semantic coverage measure. Every record
and occurrence keeps `inference_view: null`; authority remains false and training/
evaluation-gold masks remain integer zero.

## Bounds, current data scope and later work

The finite contract admits 1–4 selected manifests, at most 64 declared paired
rows per manifest, and at most 128 declared paired-row references in total.
These declared counts are bounded before reading cache files or allocating row
slots. Request bytes are at most 128 KiB; bindings are at most 512 KiB;
the complete report is at most 16 MiB. Each retained file is at most 16 MiB and
all distinct selected file descriptors together at most 64 MiB. Each public
payload call supplies a 64 MiB `max_bytes` budget, 64 paired rows, 64 MiB
`max_decoded_bytes` and an 8 MiB payload report. The existing paired-census
loader uses `max_bytes` for Arrow allocations and accumulated decoded artifact
bodies as well as transport bytes. The separate outer file checks still enforce
16 MiB per physical file and 64 MiB for all distinct selected files. The two
retained historical bundles have reported decoded requirements of 27,711,217
bytes (v1) and 22,954,637 bytes (v2), despite their smaller compressed tables.
Those requirements exceed a 16 MiB loader budget; they fit the finite 64 MiB
budget without changing the file ceiling, row bound, decoded bound or report
bound. These requirements describe retained input sizing; qualification of the
revised contract belongs to separate stage receipts.

The existing bounded ordinary-JSON rules apply,
including finite floats, strict scalar types and depth/node limits. Overflow
refuses the whole operation; no truncation or favorable subset is returned.

The retained local data selected for integration is two historical paired-v1/v2
bundles at commit `60501f3e920f6c9050cfc452e0d9fcc2b7c184f3`: six tables and sixteen
paired rows. This is a bounded diagnostic selection, not a cache census or
current-main claim. Empty explicit associations must preserve all sixteen
unresolved physical records and every original inventory occurrence. Any actual
execution, hashes, counts and resource closeout belong to separate stage receipts.

The existing materialized entity index has its own twelve-field mixed-record
schema; it is not the EntityCache queue or a definition-proof corpus. This slice
does not repeat that census or attach entities by surface-label equality.
`entity_definition_intake` stays `not_scanned`.

Remote acquisition authentication, original statutory correspondence, entity/
definition intake, independent review/access chronology, encoder receipt
attachment, governing-dependency closure, training/full-task evaluation,
convergence, Lean preservation and proof/index/capsule supervisor integration
remain separate work. Reading cached formal outputs for transport integrity is
not new model execution, a learned prediction or authority to reuse those outputs
as independently prepared source context.

## Explicit coordinate transport profile v2

The same implementation owner additionally exports
`prepare_source_context_cache_intake_v2` and
`validate_source_context_cache_intake_v2`. They take the same arguments as v1;
`source_context_cache_intake_sha256` hashes either complete report. V2 is an
explicit profile for one paired-v3 manifest with at most 64 declared physical
rows. The v1 entrypoints continue to accept paired-v1/v2 requests and refuse v3.

Use the metadata companion's
`legal-paired-manifest-inventory-request/v2` request. Its manifest entry has
exactly `path_in_repo`, `bytes`, `sha256` and
`source_coordinate_report_sha256`. The last value is an independently supplied
complete coordinate-report pin; it must agree with the v3 manifest declaration
before any table or inventory source is read. The exact manifest byte pin and
the report pin remain separate commitments.

The independent association document uses
`legal-compact-source-context-cache-bindings/v2`, with the same other fields and
complete ordered row slots as v1. It still binds the request and the unchanged
original-bound source/context inventory. Its `occurrence_ids` are caller
declarations. A valid coordinate reference does not create, select or replace
one of these inventory IDs, even when source text or legal IDs are equal.

V2 delegates to the existing metadata and payload companions' v2 entrypoints.
The payload owner validates the full report and selected occurrences through
the paired/cache owners, including unselected original document context. The
outer report embeds that payload unchanged. The complete report occurs once in
`bundles[0].payload_report.source_coordinates` as:

```json
{
  "report_raw_utf8": "exact decoded artifact JSON text",
  "report_bytes": 12345,
  "report_artifact_sha256": "exact decoded artifact-byte SHA256",
  "report_sha256": "independent complete-report pin"
}
```

These are schematic values. Keeping the original report as a string preserves
nested source-metadata order through sorted outer JSON. Reordering that metadata
can change the existing source-span identity recipe. The artifact digest, the
complete-report pin and the report's embedded content seal are distinct links.
No second full report is copied into individual records.

Each physical record additionally retains
`expected_source_coordinate_report_sha256`,
`source_coordinate_report_sha256`, `source_coordinate_span_index`,
`source_provenance_json` and `coordinate_transport_status`. Original global span
indices survive selection. A verified record has
`complete_report_occurrence_replayed` status. Missing, corrupt or unsupported
bundles retain every declared row, its expected report pin and explicit
associations, while actual coordinate fields remain null with
`cache_record_unavailable` status. Known format refusals retain the denominator;
unexpected exceptions and changing source/file witnesses still refuse the
operation.

The existing association dispositions remain source-text consistency checks.
`source_correspondence_verified` remains false, including for equal text with a
declared single association. The original inventory is replayed unchanged;
cached formal outputs, vectors and targets never become its catalog or context.
All inference views stay null, masks stay integer zero, and source, meaning,
context-permission, training and Lean authority remain false.

The report schema is `legal-compact-source-context-cache-intake/v2` and its
profile is `coordinate-bound-paired-cache-declared-associations/v2`. The report records
`paired-coordinate-transport-compatibility/v1` and strict named current producer
pins, including the coordinate replay owners. This is a reviewed source
compatibility generation, not a runtime allowlist of historical sources. Prior
pin values and source captures remain separate evidence; old qualifications do
not qualify this generation, and old report hashes are not reissued.

Existing request, file, decoded-input and complete-report ceilings remain in
force. The payload report is bounded at 8 MiB and the full context intake at
16 MiB, including the report string and escaping overhead. Overflow refuses the
whole operation. Multi-manifest coordinate intake, remote publication,
authenticated statutory occurrence joins, entity/definition interpretation,
encoder attachment, graph admission and Lean corpus admission remain separate
work.

Fresh focused qualification for this source generation passed **594 cases /
1,782 test phases**: 385 compact-content, lexical-context, original inventory,
split-membership and shared-token controls, followed by 209 legacy and coordinate
metadata, payload and cache-intake controls. The native requests select 114 and
77 test functions; the child independently checks all expanded case IDs, all
three passing phases per case and exact JUnit outcomes. No skips, deselections
or expected failures are credited. The historical retained sixteen-row external
integration case was explicitly outside this selection.

Requests, complete source manifests, actual import/compile observations, sealed
JUnit and engineering evidence, and original native/resource/source closeout
receipts are retained under
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-context-intake-20261020-01/`
(`attempt-pure-03`, `attempt-paired-03` and
`final-independent-qualification-v03.json`). Two earlier wrapper failures are
preserved separately and receive no successful qualification credit. Their
unused storage promises were released through the existing recovery owner;
all failed-attempt files remain retained. Product and test bytes were unchanged
between these attempts.

This is local engineering qualification with actual storage codecs and genuine
deterministic compiler owners. Selected package startup containers remain
isolated; numerical/model/provider execution, a wheel installation, external
statutory correspondence, source/meaning review and Lean execution are not
qualified by these checks.
