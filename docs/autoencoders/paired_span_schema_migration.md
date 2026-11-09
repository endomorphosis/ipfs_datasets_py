# Historical paired census migration

This worker upgrades one explicit historical layout. It does not run inference,
compile a span, train, open a campaign database, enqueue work, or publish.
`lake build <Lib>` remains the only Lean admission. A migrated row is not an
admission. Constitution observations must retain `roundtrip_ok=false`.

The affected historical exporter is
`93a5b6c4fafabf45f84cd12b53347e7e8e96686592b489a6a7ea036d88d5b2e9`.
It labeled bundles `uscode-paired-span-bundle/v2`, but its paired table has the
current v1 Arrow layout. Seven newer fields are missing: two learned-capture
fields and five comparison fields. This producer hashed observations with the
full v2 comparison and without the two learned-capture fields. The old Arrow
write then omitted the five comparison fields while retaining the earlier
observation ID and `exact_ast_and_validated_canonical_core/v2` method label.
Other producer/layout contracts are refused. The ordinary current loader is
unchanged and continues to reject those old files.

## Evidence preserved

The original manifest and all three original Parquet files are embedded as
bounded `historical_paired_file` artifacts, with their exact bytes, lengths and
hashes. Every original artifact row is preserved, including original producer
receipt, reports, supervisor packets and tasks. A
`paired_census_schema_migration` artifact preserves every original goal row and
maps old observation IDs to new observation IDs.

Old task packets are sealed against old observation IDs. They are never
relabelled or silently rebound. New `historical_goal_record` descriptions link
their source spans to the new census; their packet/task references are empty,
so the existing portable-goal exporter cannot treat them as newly sealed tasks.
Current repair goals are built separately by the existing paired builder.
Nothing is sent to the supervisor by migration.

The original receipt is recovered from its original artifact. An optional
retained receipt path must match those bytes exactly. The existing runner's
`exchange_rows` adapter reconstructs observations, retaining all original
guided/direct outputs and both provenance records. The existing builder
computes current canonical-core diagnostics. Missing learned captures remain
explicitly false with no learned-capture artifact. Guided agreement remains
diagnostic, not independent correctness or semantic validation.

Before writing, each new observation is projected through this exact historical
contract. The worker removes only the two learned-capture fields, clears goal
IDs, and hashes the row with its full v2 comparison. It then removes the five
comparison fields without changing that hash or the retained method label.
Every retained field and the reproduced original observation ID must match the
historical row. The lineage artifact records this pre-serialization identity
contract. A mismatch refuses migration; the worker does not copy an old ID,
search alternative hash conventions, repair, rerun, approximate, or silently
drop the mismatch.

The unchanged 64 MiB decoded-evidence limit includes all retained historical
artifacts, archival file envelopes, current goals and observations. Exceeding
it refuses this worker; there is no implicit cap increase or evidence eviction.

## Local staging

Run a fresh process with the canonical workspace tree first on `PYTHONPATH`,
under actual existing native resource/storage admission. Stop the census and
hold exact runtime owner/source-maintenance custody before installing new
source files or changing a campaign queue. Source pins must cover all paths
in `paired_span_migration.SOURCE_RELATIVES`; the prepared source-pins JSON is
bound to the candidate bytes and must be rechecked after protected deployment.
All source pins are checked again before/after writing.

Use `scripts/ops/legal_ir/migrate_legacy_paired_census.py` with:

```text
--manifest <exact-old-local-manifest>
--expected-manifest-sha256 <reviewed-old-file-sha256>
--receipt <retained-original-receipt>
--source-pins <reviewed-path-to-sha256-json>
--output-directory <owned-staging-directory-inside-native-storage-roots>
--migration-receipt <new-unique-receipt-path>
```

The original input paths remain untouched. Output names are content addressed,
and immutable output files cannot overwrite conflicting existing bytes. There
is no `--upload`, `--enqueue`, `--update-db` or model/checkpoint argument.

If original files are already published at their original paths, the optional
metadata-only download mode requires an immutable 40-hex dataset revision,
the original manifest repository path and a new download directory. It permits
only the fixed dataset and three descriptor-bound Parquet files, checks remote
sizes before download and local hashes afterward, and never downloads weights.
It does not infer missing historical remote files or substitute a newer receipt.

## Owner handoff and publication

Staging alone must not clear `needs_schema_migration`. A separately authorized
native campaign owner must compare-and-swap the exact old batch ID, old manifest
path/hash, unchanged receipt hash and migration status before replacing only
that batch's manifest pointer with the new validated manifest. Preserve the old
deferral, original files, work rows, completion counts and all unrelated rows.
The migration result provides the original batch ID, the complete new `staged`
descriptor, the exact old `supersedes` manifest/table descriptors, both
fingerprints, the unchanged receipt hash, and the lineage-artifact hash. Its
`owner_handoff` describes `needs_schema_migration` to `staged` but records no
database, work-row or completion-count changes. The worker deliberately has no
campaign database access.

Use the existing `publish_paired_manifest` path for the new bundle. Its strict
current loader validates the new rows and every artifact; the four-file atomic
publication includes historical evidence inside the artifacts table. Existing
remote readback verifies immutable hashes before any uploaded status or cleanup.
Do not mark the old manifest uploaded, or treat a failed Hub request as a local
schema migration. No custom publisher or relaxed schema validator is needed.

The old blocked batch currently has manifest fingerprint `2164feed...` and an
original receipt artifact `a160f491...`. Its local original receipt is present;
the migration need not contact Hugging Face or rerun its producer.

## Required verification before use

Prepared tests construct historical pre-serialization rows and their IDs
independently of the migration projection, then use real private legacy-schema
Parquet files: eight-span migration, exact old
artifact/goal/file retention, zero learned-capture verification, table tamper,
receipt mismatch, unsupported layout, source/observation mismatch, substituted
observation IDs or comparison methods, and bounds.
Tests grant no model, semantic, proof, Lake or training qualification. Actual
target staging must then be run under the native lease, with before/after input
hashes, current strict-loader validation, row/goal counts, memory/time telemetry
and an inspected sample of formulas and historical goal lineage.
