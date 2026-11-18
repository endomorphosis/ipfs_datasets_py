# Source-bound primary graph navigation export

`logic/autoformal/legal_primary_graph_navigation.py` adds a navigation projection
to the existing [manifest-selected reconstruction](legal_primary_graph_reconstruction_20261013.md).
It does not add a graph authority or infer missing identifiers from labels.
The original entity cache and retained shards remain unchanged.

## Input and output contracts

Supply a selection produced by `select_primary_graph_manifest`, independently
pinned by `expected_selection_sha256`, its original snapshot, and an optional
same-repository Hugging Face blob root. The writer calls the existing complete
reconstruction owner. It requires complete population coverage, unique declared
identities, resolved declared endpoints and no reconstruction blockers before
publishing a navigation bundle.

`write_navigation_bundle(selection, snapshot_root, new_output_directory, *,
expected_selection_sha256, blobs_root=None, limits=None,
reconstruction_limits=None)` exclusively creates a new directory containing:

| File | Meaning |
| --- | --- |
| `primary-records.jsonl` | Every selected primary row, including original parsed properties, physical source custody, edge identities and ordered population commitments. |
| `reconstruction.json` | The existing reconstruction owner's complete report and candidate hash. |
| `navigation.parquet` | Twelve navigation fields compatible with the existing materialized entity-index census. |
| `manifest.json` | The final bundle commitment, including exact source selection, release identity, output hashes/counts, implementation pins, limits and false authority flags. |

Node `node_id` comes directly from `entry_cid`. Edge `src` and `dst` come directly
from `source_entry_cid` and `target_entry_cid`. Each edge's own identity remains
in the paired primary record. Labels and optional legal IDs do not replace these
identifiers. Known category/relation mappings come from `meta_ontology`; unknown
kinds remain explicitly unclassified. No category or relation-description rows
are inserted into this source-row population.

All rows have `in_formula=False`, `admitted=False` and `formalized=False`, including
`CITES` edges. A declared citation relationship is not an admitted formula. The
existing intake may consequently report disagreement with its historical
`in_formula=True` hint for that relation; that observation does not change these
authority flags.

The companion preserves complete **parsed** properties and source commitments.
Exact original `record_json` bytes, including whitespace, remain in the required
pinned source shards. The twelve-column Parquet file alone is not a lossless
graph exchange or a complete legal corpus. Preserve the companion and original
source dependencies when moving or publishing an export.

## Independent replay and bounded execution

`validate_navigation_bundle(directory, *, expected_manifest_sha256, selection,
snapshot_root, expected_selection_sha256, blobs_root=None, limits=None,
reconstruction_limits=None)` verifies the independently supplied manifest pin,
replays the complete original selected source through `validate_reconstruction`,
and compares every navigation row against its paired record in order. Output
counts, schema, multiplicity, authority flags and source/implementation bindings
must match. Rehashing an altered export does not make it equal to its source.

The producer returns the manifest and its SHA-256. Keep that commitment outside
the bundle before validation. Use the same explicit limit profiles and recorded
implementation sources when replaying. The implementation pins include actual
loaded source paths as well as their hashes; copied source trees are different
execution provenance even when individual files have matching contents.

Bounds cover candidate/index/report sizes, row and row-group populations,
decoded data and batches. Reconstruction retains its own file, scratch and row
bounds. The writer refuses existing outputs and source-root destinations. File
descriptors and identity checks protect input reads and publication. The manifest
is published last. Failure does not publish a qualified partial bundle; an
already completed reconstruction may remain as a diagnostic, and foreign files
are not recursively removed.

Run full export, replay and census under the existing shared validation resource
lease. These APIs do not initialize a scheduler or change admission policy. A
resource limit failure is a failed attempt, not evidence that a partial export
passed. The focused tests are in
`tests/unit/logic/autoformal/test_legal_primary_graph_navigation.py`.

## Scope before legal training and Lean

This export covers the exact manifest-selected primary graph. It cannot silently
replace the larger historical materialized cache or recover missing IDs in
unselected legacy shards. Unresolved citation placeholder nodes remain unresolved
even when edges correctly point to their declared identifiers.

Source-occurrence binding, reviewed definitions and norms, scoped term resolution,
typed LegalIR assertions, checkpoint qualification and Lean lowering/builds are
separate downstream steps. No transport or navigation result grants those stages
authority. Continue through the existing LegalIR implementation backlog and
source-review owners rather than treating graph rows as training gold.
