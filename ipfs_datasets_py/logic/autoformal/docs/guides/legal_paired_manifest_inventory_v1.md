# Selected paired manifest inventory

This stateless adapter inventories an explicitly selected set of pinned paired-v1/v2 manifests from `justicedao/uscode-autoformal-span-cache`. It reuses the existing span feed's manifest parser and descriptor checks. It does not instantiate a feed, create a database, fetch files or read table bodies.

## Input and replay

The request declares one immutable repository commit, the `explicit_paired_manifest_selection` scope and an ordered list of manifest paths, exact byte sizes and independently supplied SHA256 values. Supply the corresponding exact raw manifest bytes as a separate dictionary keyed by repository path. Missing or extra bytes, duplicate paths, unsupported fields, invalid paths, changed hashes and bound overflow fail before producing a report.

The public module is `ipfs_datasets_py.logic.autoformal.legal_paired_manifest_inventory_v1`. Its prepare and validate functions require independently supplied request/report identities. Validation replays the original request and complete raw manifest population; rehashing an altered report does not make it valid. Original manifest UTF8 text is retained. Producer identities come from trusted local modules and are checked before and after preparation. Offered report paths do not select files to open.

Manifest validation delegates to `span_cache_feed._manifest_json`, `_manifest_match` and `_paired_descriptors`. These preserve the existing namespace/schema, producer, content fingerprint, table kinds, path/filename/digest, size/count and false authority checks. The request separately binds the manifest transport hash, repository and revision. A self-derived manifest fingerprint is not evidence that its table bodies match the declarations.

The first profile supports at most 16 selected manifests, 64 KiB per manifest and 512 KiB in aggregate. Requests are bounded to 128 KiB and complete reports to 4 MiB. Empty selections are permitted as empty caller selections; they say nothing about the repository's contents. No input is silently truncated.

## Counts and boundaries

For each bank version and table kind, retain separate counts for manifest references, declared row references, distinct physical table paths and rows declared by distinct paths. Byte totals follow the same distinction. Repeated references to one identical descriptor remain visible without increasing the distinct-path totals. Conflicting descriptors for one path fail. Equal declared content hashes at different paths do not merge physical files or source occurrences.

All row and byte counts are **manifest declarations**. Table bytes, Arrow schema, row identities, artifact/capture integrity and reciprocal goal links have not been checked. Unique source occurrences and unique attempts remain unknown. The report accounts for the complete supplied selection; it does not claim complete pagination, whole-repository discovery, viewer coverage or formalized-law coverage. Legacy exchange banks are outside this first profile.

Historical v2-labelled bundles may have exporter-specific Arrow layout loss. The available `paired_span_migration.py` owner handles a particular declared historical exporter. Manifest metadata alone cannot establish that migration's eligibility or repair the payload. Keep that question unknown until the existing payload worker is explicitly applicable.

No source occurrence, governing definition, legal meaning, review, graph/Lean admission or training gold is inferred. Qualification flags and training/evaluation masks remain false or zero.

## Existing owners for subsequent work

Use `SpanCacheFeed` for bounded pinned discovery and durable delivery, and `paired_span_census.load_paired_census_bundle` for actual table and artifact validation under its supported profiles. A metadata report does not substitute for either operation.

For physical source custody, reuse `corpus_span_adapter.adapt_paired_span_bytes` with its explicit six-field source binding and full replay. The historical flat-cache route already has `legal_cache_parent_occurrences` and `corpus_parent_occurrence_adapter`, retaining every zero/single/multiple exact-match disposition without selecting a governing occurrence. Sampled review-to-original-primary association is another existing route. Matching text, section labels or historical IDs does not make those source generations equivalent.

After source and meaning decisions are supported, the existing typed graph, scoped-definition and Lean owners supply later stages. This inventory adds a metadata boundary before those stages and changes none of their contracts.

## Explicit coordinate metadata profile

`prepare_paired_manifest_inventory_v2` and
`validate_paired_manifest_inventory_v2` share the existing bounded engine. They
accept request schema `legal-paired-manifest-inventory-request/v2` and produce
`legal-paired-manifest-inventory/v2`. This profile accepts only paired-v3
manifest paths; the original entry points retain their paired-v1/v2 path and
report contracts.

Each selected entry has exactly `path_in_repo`, `bytes`, `sha256` and
`source_coordinate_report_sha256`. The last value is an independently retained
complete coordinate-report commitment. The manifest's `coordinate_transport`
must declare exactly `schema`, `report_artifact_sha256`, `report_sha256` and
`index_artifact_sha256`, with schema `paired-source-coordinate-transport/v1`.
All three digests are lowercase SHA256 values; `report_sha256` must equal the
independent selection pin. The report artifact hash and complete-report pin
are separate identities and need not equal each other.

The feed owner still checks namespace/schema, producer, fingerprint and all
three table descriptors. Only the `paired-v3` bank appears in v2 analysis.
This operation reads no tables or report/index artifacts, performs no source
replay and grants no source or context authority. Use the explicit v2 payload
intake to replay the full report. These source changes require fresh engineering
qualification; historical receipts remain tied to their original source pins.
