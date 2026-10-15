# Primary graph candidate export

[`legal_primary_graph_export.py`](../../ipfs_datasets_py/logic/autoformal/legal_primary_graph_export.py)
transports a complete, independently selected population of original primary
graph occurrences into a new candidate generation. It preserves the original
record bodies and custody while declaring the release writer's canonical JSON
encoding transformation. It does not reconstruct historical flat-cache links,
merge entities by label, or admit a graph for legal or training use.

The format is `legal-primary-graph-export/v1`, with profile
`manifest-selected-primary-entry-cid-canonical-parquet/v1`. Its identity namespace
is explicitly `primary_entry_cid`: legal IDs and labels are retained properties,
not substitute node identities. Other record-CID or node-CID namespaces are not
implicitly interchangeable with this one.

`graph_nodes` and `graph_edges` are transport families. They do not declare FOL,
TDFOL, deontic, temporal, cognitive, or Lean capabilities; those remain separate
interpretation and compiler contracts.

## Inputs and API

Execution belongs inside the existing native validation owner, with its frozen
request, source pins, admission, resource reservation, and closeout. This module
does not acquire a grant or provide an independent workload launcher.

The source selection must come from the existing
[`select_primary_graph_manifest`](../../ipfs_datasets_py/logic/autoformal/legal_primary_graph_manifest.py)
owner. That owner requires independently expected raw manifest SHA-256,
repository and immutable 40-hex revision, release identity, and graph-family
file/row populations. Membership follows the exact manifest descriptors. Extra
retained files remain separate observations; they do not become members through
a prefix glob. The supplied snapshot and optional blob root must remain immutable
and satisfy the existing source custody checks.

The API shapes below describe calls made by the admitted owner; they are not a
standalone execution recipe:

```python
export_primary_graph(
    selection, snapshot_root, new_output_directory,
    expected_selection_sha256=accepted_selection_sha256,
    blobs_root=None, source_limits=None, limits=None,
)

validate_primary_graph_export(
    output_directory,
    expected_manifest_sha256=accepted_export_manifest_sha256,
    selection=selection, snapshot_root=snapshot_root,
    expected_selection_sha256=accepted_selection_sha256,
    blobs_root=None, source_limits=None, limits=None,
)
```

Use the accepted selection and its separately frozen expected digest. Rehashing
an arbitrary selection does not establish independent source membership. The
exporter returns the exact `manifest_sha256`, `manifest_bytes`, parsed `manifest`,
and status `candidate_export_complete`. The supervising owner must retain and
review that digest in independently accepted producer evidence before using it
as the reader's expected export-manifest pin. Computing a digest from whichever
`manifest.json` is currently present establishes self-agreement only.

Validation requires both the separately expected export-manifest digest and the
original immutable selection/source. Its successful result has status
`candidate_export_verified` and `fresh_original_replay_performed: true`. This is
a transport verification result, not legal acceptance. Contract mismatches raise
`PrimaryGraphExportError` (`ValueError`); existing owner and I/O failures also
propagate. There is no new source-selection, custody, census, or identity-resolution
engine: those responsibilities remain with the existing manifest, strict-record,
and global reconstruction owners.

## Files and exact lineage

The new directory contains only:

| File | Contents |
| --- | --- |
| `manifest.json` | Canonical UTF-8 JSON plus newline; complete companion inventory, source/reconstruction pins, populations, dispositions, limits, and authority. Its exact SHA-256 is retained externally. |
| `reconstruction.json` | The complete existing-owner reconstruction report. |
| `lineage.jsonl` | One header followed by one row per physical original occurrence, in selected source order. |
| `graph_nodes-NNNNNN.parquet` | Bounded node occurrences written by the unchanged release writer. |
| `graph_edges-NNNNNN.parquet` | Bounded edge occurrences written by the unchanged release writer. |

No empty Parquet shard is emitted for an empty family. File descriptors contain
exactly `path`, `kind`, `family`, `rows`, `bytes`, and `sha256`; lineage row counts
exclude its header. Temporary `reconstructed.jsonl` is not a final artifact.

Each Parquet row has the original writer's five string fields: `entry_cid`,
`legal_id`, `family`, `record_sha256`, and `record_json`. The strict expected
wrapper is independently derived from the original decoded body using the
existing normative `canonical_json_bytes` codec. The actual original release
writer produces the Parquet bytes. A writer fallback such as `term` to `legal_id`,
or any other wrapper/body discrepancy, refuses finalization; fallback behavior
is not treated as identity validation.

Lineage header schema is `legal-primary-graph-export-lineage-header/v1`; row
schema is `legal-primary-graph-export-lineage-row/v1`. Every row retains:

- `global_ordinal`, the exact `original_raw_wrapper`, and the complete
  `reconstruction_row`, including physical custody, raw-row/record hashes,
  identity/endpoint resolutions, and disposition.
- `exported_wrapper` and `export_location` (`file`, zero-based `row_ordinal`), or
  null when the occurrence cannot be decoded for transport.
- `encoding_transformation`, or null, with original/exported record and raw-row
  hashes plus explicit `record_json_changed` and `record_sha256_changed` flags.
- The original reconstruction `disposition` and an explicit `quarantined` flag.

Noncanonical original `record_json` whitespace is preserved exactly in
`original_raw_wrapper`. Canonical output can therefore have a different
`record_json`, record hash, and raw-row hash. This is a declared
`canonical-json-encoding-only/v1` transformation, not original wrapper byte
parity. The parsed body must retain every field and JSON type exactly, including
opaque role, ordinal, source, and evidence properties. Boolean/integer/float
substitutions are not equal transport data.

## Quarantine and population accounting

No deduplication occurs. Decoded duplicate identities, conflicting identities,
and dangling/ambiguous endpoint occurrences remain individually transported and
explicitly quarantined under the existing global dispositions. Undecodable or
malformed bodies remain lineage-only, with their complete original wrapper and
unresolved reconstruction observation. They are not silently dropped or coerced.

`source_rows` always covers the complete selected population.
`exported_rows + lineage_only_rows == source_rows`; quarantined observations can
be in either category. Per-family, encoding-transformation, and disposition
counts remain explicit. Any reconstruction blocker makes
`structural_endpoint_integrity_passed` false. Even when that structural check
passes, `accepted_graph_view_enabled` remains false and the view is
`candidate_transport_only`.

## Independent readback

The public validator rebuilds reconstruction from the independently supplied
original selection and immutable source, then compares the complete saved report
and every lineage occurrence against that fresh replay. It independently derives
canonical wrappers and shard placements from those originals. It regenerates
each shard with the actual unchanged writer and requires its exact byte length
and SHA-256 to match before opening the saved Parquet for decoded batches.

Arrow readback then checks the exact five-string-field schema, finite footer
row/column populations and uncompressed byte totals before batch decoding,
followed by bounded batches, strict payload decoding, exact wrappers/bodies, and
complete row/order/location parity. File hashes and a resealed manifest alone
cannot establish original-to-export equality. Unknown files, missing occurrences,
changed roles/source properties, type-altered authority, and other original-bound
discrepancies refuse verification.

Exact Parquet byte replay deliberately requires the unchanged writer and
compatible Arrow encoding environment. A library/writer change may reject a
semantically identical serialization. Such a generation needs separately
qualified producer/profile evidence; this validator does not relax byte custody
or silently accept a new encoding profile.

## Finite bounds and lifecycle

All export overrides are positive exact integers no larger than these defaults;
unknown keys, booleans, and ceiling increases are refused. The validator requires
the same effective export limits as the manifest.

| Export limit | Default ceiling |
| --- | ---: |
| `max_rows` | 400,000 |
| `max_shards` | 1,024 across both families |
| `rows_per_shard` | 512 |
| `max_shard_input_bytes` | 8 MiB |
| `max_parquet_bytes` | 64 MiB per shard |
| `max_output_bytes` | 1 GiB per final generation |
| `max_lineage_line_bytes` | 8 MiB |
| `max_manifest_bytes` | 1 MiB, also bounding `reconstruction.json` |
| `batch_size` | 512 rows |
| `max_decoded_batch_bytes` | 16 MiB |

Writer input row/byte sums are checked before encoding. Footer uncompressed
totals and aggregate decoded shard bytes are also bounded by
`max_shard_input_bytes`. Companion/lineage output is budgeted before each staged
write; the complete manifest is included in the final-generation total. Directory
inventory iteration is bounded before materialization.

These are distinct from `source_limits`, delegated unchanged to reconstruction
and its manifest owner. Their existing source-file, row, decoded-byte, scratch,
candidate-output, and line ceilings still apply. Export `max_output_bytes` does
not include temporary reconstruction output, reconstruction scratch, replay, or
simultaneous staging/publication copies. The admitted native parent must reserve
that combined peak, together with process memory, CPU, and child resources. Arrow
batch/footer checks are not a whole-process memory reservation.

The output must be a new, unaliased directory under an existing unaliased parent,
outside immutable snapshot/blob roots. Existing destinations are refused. Files
are created exclusively, guarded against symlinks and path/inode changes, and
read as bounded single-link regular files. The exporter performs complete
original-bound readback in staging and after exclusive copying, then writes the
manifest last and checks the final closed inventory. Readers must require the
independently accepted manifest pin and full validator; an incomplete directory
is not a usable generation.

Caught failures clean up only files/directories still proven to be the unchanged
owned inodes. Foreign replacements and nonempty foreign directories are
preserved. Interrupted or tampered work can therefore leave nonfinalized
artifacts for the native owner's review; cleanup never guesses ownership or
deletes foreign entries. The original source and an existing destination are
never mutation targets.

## Authority and evidence boundary

All of the following remain false in every export: `admitted`, `formalized`,
`source_semantics_verified`, `semantic_review_verified`, `training_qualified`,
`proof_authority`, `accepted_graph_view_enabled`, `published`,
`historical_flat_occurrences_repaired`, and
`source_population_equivalence_verified`.

The format preserves selected primary-source transport and observations. It does
not demonstrate actual historical entity-cache lineage, repair every flat-cache
occurrence, establish whole-corpus equivalence, prove legal meaning, qualify
training examples, or produce an accepted Lean corpus. A successful Lean build
would establish only the stated elaboration/proof obligations under its
assumptions; source fidelity and legal interpretation require separate evidence.

## Qualification on October 15, 2026

The native owner completed the selected authored-fixture qualification with
**160 distinct cases passing**: 51 exporter, 45 strict-record, 38 citation-reader,
and 26 selected reconstruction cases. The [frozen request](evidence/legal-primary-graph-export-20261015/validation-request-v02.json)
binds 80 source inputs. The [child receipt](evidence/legal-primary-graph-export-20261015/attempt02/qualification.json)
joins actual collected cases, successful calls and JUnit identities, checks all
loaded product origins against checked source buffers, and records zero network
or extra child-process attempts. The complete new exporter suite ran. One
existing reconstruction test deliberately creates a symlink and was excluded
because this native profile requires regular-file inventories; its source
remains unchanged and it is not counted as executed.

The parent [execution](evidence/legal-primary-graph-export-20261015/attempt02/execution.json),
[durability inventory](evidence/legal-primary-graph-export-20261015/attempt02/validation-durability.json),
and [exact captured terminal output](evidence/legal-primary-graph-export-20261015/native-parent-output-v02.json)
record completion, a stopped process group, durable artifacts, released storage
and native lease, and no cleanup error. The final retained attempt occupied
2,572,333 bytes within its 512 MiB storage reservation; it also reserved 4 GiB
memory, one CPU and one child slot. Supervision remains cooperative and sampled.
The captured release is owner evidence, not independent live-ledger authentication.

Attempt 01 also passed the same 160 test cases, then failed a closing guard.
Its [failed receipt](evidence/legal-primary-graph-export-20261015/attempt01/qualification-failed.json)
and recovery evidence are preserved, and the attempt remains failed. Static
analysis identified pytest assertion rewriting as a possible competing import
hook, but the original helper did not record the exact failing predicate.
Attempt 02 added granular diagnostics and `--assert=plain`, retaining ordinary
Python assertions and all acceptance guards. Its success does not prove the
precise cause of attempt 01. The two runs are not 320 distinct cases.

The [independent metadata recount](evidence/legal-primary-graph-export-20261015/independent-metadata-review-v02.json)
checks case identities, source pins and the recorded native closeout without
executing product code or reopening fixture payloads. The
[upstream reconciliation](evidence/legal-primary-graph-export-20261015/upstream-reconciliation.json)
preserves the parallel V2 definition/use adapter while confirming all 80
qualification pins unchanged. That incoming adapter was not executed by this run.
The [publication manifest](evidence/legal-primary-graph-export-20261015/publication-manifest.json)
binds the selected evidence copies. Absolute-path drivers and requests are
historical evidence; another run needs a newly frozen request and admission.

This qualification executes authored fixtures. No production primary-graph
generation, historical flat-cache repair, statutory review, decoder training,
accuracy improvement, model upload or Lean build occurred. The next corpus job
must freeze its original source selection and full peak resource budget, run
this exporter and original-bound validator under the existing owner, and retain
the complete population/quarantine result. Historical flat-cache occurrence
lineage and multiplicity require their own supported reconciliation.
