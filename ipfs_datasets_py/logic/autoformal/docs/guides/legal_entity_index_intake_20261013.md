# Materialized legal entity-index intake

`logic.autoformal.legal_entity_index_intake` observes the Hub's materialized
`kg-logic-index.parquet` without converting it into the local EntityCache
queue/resume schema or asserting legal meaning. The supported ordered columns
are `record_kind`, `meta_category`, `graph_kind`, `label`, `legal_id`, `node_id`,
`src`, `dst`, `logic_role`, `in_formula`, `admitted`, `formalized`. String and
boolean nulls remain null; unsupported fields/types are refused before decoding.

## Immutable file census

Retain an independently trusted file-custody record with full SHA-256, expected
row count and exact Hub revision. The observed 2026-10-13 snapshot has revision
`97978d033f42014fcf84f8541b55e53630164823`, 16,898,459 bytes and 1,960,876 footer
rows. Those metadata facts do not establish source completeness or semantics.
Run the census only within the supervisor's bounded validation resource lease.

```python
import json
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as intake

custody = json.loads(Path("entity-index-custody.json").read_text())
trusted = dict(expected_file_sha256=custody["sha256"],
    expected_rows=1_960_876, revision=custody["revision"],
    max_rows=2_000_000, batch_size=512, max_file_bytes=20 * 1024 * 1024)
report = intake.census_parquet(custody["local_path"], **trusted)
Path("entity-index-census.json").write_text(json.dumps(report, sort_keys=True))
# A separate protected job receipt must retain report["census_sha256"].
```

The scanner verifies file hash, ordered schema, footer population and decoded
size bounds before traversing. It uses bounded Arrow batches and temporary,
size-limited on-disk SQLite for raw-row duplicates, declared node identities and
endpoint resolution. It rechecks descriptor/path identity and hashes the entire
file again before returning. It holds no complete row population in Python RAM.
Optional limits are `max_decoded_bytes`, `max_row_group_bytes`, `max_batch_bytes`,
`max_row_bytes`, `max_scratch_bytes`; exceeding any bound fails without a partial
census. Defaults are finite ceilings, and callers can lower them.

The deterministic report includes all record-kind counts, null/empty-field
counts, exact exclusive dispositions, legacy boolean observations, duplicate
counts, endpoint gaps and an ordered raw-row stream hash. `node`, `edge`,
`category`, `logical_relation`, `classification_rule`, `term` and `link` are observation kinds; other
kinds remain explicitly unknown observations. Unknown labels/categories are
retained. Existing `meta_ontology` mappings supply declared hints only.

Missing node IDs remain missing. Missing endpoints remain unresolved, and
duplicate declared node IDs make matching endpoints ambiguous. Labels never
synthesize IDs, resolve endpoints or merge entities. The completed census of
this exact pinned snapshot observed the following physical population:

| Record kind | Rows |
| --- | ---: |
| `node` | 238,452 |
| `edge` | 1,722,395 |
| `category` | 9 |
| `logical_relation` | 6 |
| `classification_rule` | 14 |

Of the node observations, 119,134 have missing IDs and 119,318 have nonempty
IDs. All 1,722,395 edge observations have unresolved endpoints. Across the
entire file, `src` and `dst` are each empty in 1,960,870 rows; the six nonempty
cases belong to logical-relation metadata. There are 1,722,389 duplicate raw-row
instances beyond their first occurrences. These remain observations; duplicates
are counted, never dropped. Repair requires investigating the upstream exporter,
not reconstructing identifiers from display labels. Recognizing a classification
rule record does not execute it or accept its proposed meaning.

## Lossless row traversal

```python
for observation in intake.iter_observed_rows(custody["local_path"], **trusted):
    raw_row = observation["raw_row"]
    # Consume bounded rows incrementally; do not accumulate the entire file.
    assert observation["authority"]["typed_graph_assertions_generated"] is False
```

Each envelope retains every raw field, global zero-based ordinal, row-group and
local ordinal, file/revision custody, canonical raw-row hash and distinct
observation hash. Repeated identical rows retain separate physical identities.
Canonical JSON uses sorted keys, compact separators and finite UTF-8 values.
Canonical-row byte counts and hashes do not claim row byte offsets inside the
compressed Parquet file. Original file bytes remain the lossless physical source.
Exhaust the iterator for a complete traversal; individual yielded rows never
attest population coverage. Use the census for a final coverage report.

## Full replay and later binding checks

```python
# Independent qualification replays all rows and compares the complete report.
intake.validate_census(report, custody["local_path"], **trusted)
# Later idempotent checks require a separately retained trusted census pin.
expected_pin = Path("protected-census-pin.txt").read_text().strip()
check = intake.validate_census_bindings(report, custody["local_path"],
    expected_census_sha256=expected_pin, **trusted)
assert check["fresh_row_replay_performed"] is False
```

Binding checks verify the independent prior census hash, rehash current file
bytes and replay schema/footer/limits. They do not rerun row classification.
Never use an incoming report's own hash as its independent expected pin.
Changing traversal limits or revision changes the expected report contract.
Reports contain no elapsed times or temporary paths; equal pinned inputs and
limits produce repeatable JSON.

## Detailed endpoint diagnostics (explicit v2)

Use `endpoint_details=True` for a versioned census that distinguishes absent
endpoint values from references to node IDs that are not present. Default calls
still produce the original v1 schema, fields and hashes.

```python
report = intake.census_parquet(custody["local_path"], endpoint_details=True, **trusted)
assert report["schema"] == "legal-materialized-entity-index-census/v2"
details = report["endpoint_integrity"]
assert sum(details["exclusive_edge_dispositions"].values()) == details["edge_rows"]
```

The four exclusive dispositions, in precedence order, are:

1. At least one null or empty endpoint value.
2. Both values are nonempty, but at least one has no matching declared node ID.
3. Both values match declared IDs, but at least one ID names multiple node rows.
4. Both values match exactly one declared node row each.

Counts retain repeated physical edges. Separate per-endpoint diagnostics can
overlap: an edge may have an empty source and a nonempty dangling target. Only
`record_kind=edge` contributes; ontology/logical-relation metadata is excluded.
Identifiers use exact string equality with no whitespace normalization, label
matching or inferred IDs. Matching declared IDs does not verify semantic identity.

Both validators require the explicit v2 request. For a later binding check, use
the independently retained **v2** census pin:

```python
intake.validate_census(report, custody["local_path"], endpoint_details=True, **trusted)
intake.validate_census_bindings(report, custody["local_path"], endpoint_details=True,
    expected_census_sha256=expected_v2_pin, **trusted)
```

Closed detail fields, fixed matching policy, false semantic authority and exact
nonnegative integer counters are checked even when a supplied digest matches.
Binding validation still does not perform a fresh row traversal. The
[2026-10-15 qualification report](../../../../../docs/autoencoders/legal_ir_cache_source_qualification_20261015.md)
records the newer pinned export's complete census and its remaining source gaps.

## Graph aggregation boundary

`population_complete` covers the exact pinned Parquet row population only.
Legacy `in_formula`, `admitted` and `formalized` values remain raw observations;
all intake authority flags remain false. The intake does not generate typed
assertions, attach governing definitions, establish a complete statute population,
backfill caches or export Lean 4. To build graph proposals, supply independently
bound official source occurrences, explicit AST/scope declarations and complete
expected occurrence inventories through the
[proposed graph aggregation APIs](../../../../../docs/guides/legal_proposed_graph_aggregation_20261013.md).
Independent semantic review remains necessary before accepting legal assertions;
neither structural transport nor a legacy index flag supplies that review.
