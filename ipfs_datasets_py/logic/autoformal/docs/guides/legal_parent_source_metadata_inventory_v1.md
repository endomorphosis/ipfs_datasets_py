# Saved historical-parent metadata inventory

`ipfs_datasets_py.logic.autoformal.legal_parent_source_metadata_inventory_v1`
reads the saved package emitted by `legal_parent_parquet_pages.scan_parent_source_metadata`.
It returns a distinct immutable `HistoricalParentSourceInventory` and prepares
the complete physical population's known grouping keys and unresolved obligations.
This interface performs no parent Parquet decoding, source text reconstruction,
model/database/prover operation or split assignment.

```python
inventory = load_parent_source_metadata_inventory_v1(
    absolute_manifest_path,
    expected_manifest_sha256=raw_manifest_file_sha256,
    expected_parent_descriptor_sha256=independent_descriptor_sha256,
    expected_preflight_report_sha256=independent_preflight_report_sha256,
    limits=ParentSourceMetadataInventoryLimits(),
)
preparation = prepare_parent_source_grouping_v1(inventory)
```

The manifest must retain its producer basename `parent-source-metadata.json`.
The package consists of that file and the `metadata` directory, with exactly the
declared ordered `metadata/part-000000.jsonl`, `part-000001.jsonl`, … roster.
The reader refuses extra/missing members, path traversal, symbolic-link aliases,
hard-linked files and nonregular files. Input file and directory opens use explicit
absolute paths. Held physical directory/file descriptors, path identities and
final member/roster checks detect replacement during a successful load. These are
ordered custody checks, not a filesystem-wide atomic snapshot guarantee.

## Pins and validation

`expected_manifest_sha256` hashes the exact canonical sorted-key UTF-8 JSON file
**including its single final LF**. It differs from both the manifest's internal
`manifest_sha256` (canonical object excluding that field) and the full canonical
object hash returned by the producer's public hash helper (including the field,
excluding LF). All three identities are checked and exposed separately.

The descriptor and preflight hashes are mandatory independent caller inputs.
The descriptor is closed and canonically regenerated; its hash must match its
independent pin. The preflight hash must equal the manifest's recorded reference.
The loader does not open the preflight body or the declared `parent.local_path`.
It therefore does not independently establish original page geometry, historical
execution, current parent bytes, official edition correspondence or source truth.

Validation covers:

- Closed manifest/profile/schema/normalization/limits fields, internal seal and
  exact raw file pin; complete parent and shard denominator/accounting.
- Canonical source schema, ordered unique field indices and supported physical
  types; complete unique page-witness identities/locations, column coverage and
  decoded-byte totals. Page hashes remain pinned producer observations.
- Bounded canonical JSONL records and complete contiguous physical ordinals;
  each full physical key and its SHA-derived physical section ID.
- Full raw-row hash shape and canonical-byte accounting, text hash/statistics
  consistency, empty versus missing/unsupported text and observed identity
  literals/statuses/overlong-value evidence.
- Exact all-false authority fields, plain integer-zero training/gold masks and
  null group/split/inference fields, at both manifest and row boundaries.
- Full shard byte/hash checks and final package member/roster/limit stability.

Raw-row/text/normalized/page digests cannot be recomputed from metadata alone.
The loader verifies custody and internal consistency of those scanner
observations, not the source values they commit to. A coherent newly supplied
package still needs its own independent acquisition/qualification evidence.
`source_schema` preserves the declared complete field population: the actual
historical package has 45 fields, while smaller independent format fixtures can
declare a smaller supported population.

## Immutable inventory

Only the public loader constructs the exact inventory type. It retains the
bounded manifest and compact immutable per-row bytes, omitting repeated parent,
authority and null fields. It retains no source text, source raw-row values or
original complete JSONL lines. Frozen state protects normal public API mutation;
this snapshot is not an isolation boundary for arbitrary reflective Python code.

- `row_count` is the complete verified saved population.
- `sha256` / `manifest_file_sha256` are the raw manifest file hash including LF.
- `manifest_canonical_sha256` hashes the full object without LF.
- `internal_manifest_sha256` returns the producer's internal seal.
- `manifest` returns a detached original manifest dictionary.
- `to_dict()` returns a detached bounded inventory summary, without all rows.
- `iter_rows()` reconstructs detached source metadata rows, preserving the
  producer's complete physical key, observations, statuses and source-only flags.

The summary reports `package_custody_verified=true`,
`current_source_bytes_verified=false` and
`scanner_row_hashes_independently_recomputed=false`. The distinct type is not a
release `USCodeSourceInventory`, existing `SourcePartitions`, an admission
capability or a training/evaluation authorization.

Iteration preserves scanner observations; it does not turn the retained thirteen
independent row/text oracles into independent verification of all other rows.

## Grouping preparation

`prepare_parent_source_grouping_v1(inventory)` retains one row per physical
occurrence, in order. Each row includes its physical section ID, ordinal, full
raw-row hash, disposition, three key slots, an opaque CID observation, explicit
blockers and null/zero source-only fields. Keys are:

```json
{"document":null,"exact_text_sha256":"… or null","normalized_content_sha256":"… or null"}
```

Document identity is unresolved for **every** row in this profile. CID/title/
section observations do not establish missing edition, appendix, note, granule
or other qualifiers. No independent identity-binding API is implemented here.
The CID is an opaque observation with no inferred referent or equality to text,
row or document identity. The Parquet artifact hash is custody and never a shared
text key that would collapse the parent into one group.

Every row therefore has `document_identity_unresolved`. Missing/unsupported text
also produces `exact_text_unavailable` and `normalized_content_unavailable`.
Genuine empty text retains its real empty hashes. Null is an unresolved obligation:
it is neither empty text nor a grouping key shared by unknown rows. This module
does not call the connected-component assigner, create substitute singleton
groups, select aliases, filter excluded connectors, reseed or assign splits.

The report supplies the complete row roster, `key_availability_counts`,
`blocker_counts`, `all_required_keys_available=false` and
`complete_source_partitions_constructed=false`. `preparation_sha256` hashes the
canonical report excluding that field; `parent_source_grouping_sha256(report)`
hashes the complete canonical report including it. This hash helper alone does
not validate the report against original package files.

For the qualified 60,077-row parent, nine missing-text occurrences also have
missing CID/title/section observations. They remain in the denominator. The
different 62,931-row release cannot supply their identities or partition
assignments. Independently pinned lineage, legal context/dependency closure,
governing interpretation review and scientific eligibility are later contracts.

## Finite resource contract

`ParentSourceMetadataInventoryLimits` is a frozen exact-type dataclass. Every
field must be a positive plain integer at or below its fixed ceiling. It is
revalidated before serialization and at successful closing fences. Its ceilings
are 65,536 rows, 2 MiB manifest, 4 KiB JSONL row, 4 MiB shard, 128 shards, 384 MiB
complete saved package, 128 MiB retained compact summaries and 64 MiB canonical
grouping preparation. Producer-declared limits may lower applicable bounds.

Files are streamed through bounded row reads; directory entry enumeration is
also bounded. The complete preparation is an explicitly bounded in-memory
metadata roster. Canonical byte bounds do not measure Python allocator overhead
or establish peak RSS. A genuine execution requires the existing source/native/
storage admission and an appropriate separately owned runtime envelope. A test
may retain only bounded counters/digests plus selected independent oracles rather
than duplicate the complete preparation on disk. This guide grants no runtime,
scientific, Lean, convergence or publication credit.

## Portable tests and retained-package replay

The default test selection uses small independently authored saved-format
packages. It exercises immutable inventories, grouping blockers, finite limits,
tampering, aliases and input mutation without requiring the historical source
Parquet or its metadata package.

A four-row Parquet fixture also exercises the actual scanner → saved loader →
grouping preparation path. It preserves distinct duplicate occurrences, Unicode
text, empty versus null text, unresolved document identities and zero authority
masks across two saved shards.

The historical 60,077-row case is marked `integration` and `heavy` and skips
unless `LEGAL_PARENT_METADATA_LOADER_ENROLLED=1`. Normal pytest also requires
its existing `--run-heavy` option or `RUN_HEAVY_TESTS=1`. Setting these markers alone
does not grant resource or source admission. An explicitly owned replay must
also supply `LEGAL_PARENT_METADATA_LOADER_INPUTS` naming the exact pinned
request and admit every referenced saved shard and independent oracle through
the existing native validation owners. Once enrolled, missing files or wrong
pins fail; the original test assertions remain intact.

The retained original qualification passed 51 cases including that full saved
package. Portable integration reuses its evidence and skips the full replay;
it does not claim to reverify the 60,077 rows or add independent row oracles.
Document identity remains unresolved for every historical row, and nine rows
retain missing text. These outcomes do not change when this loader is installed.
