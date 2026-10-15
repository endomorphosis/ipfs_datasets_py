# Preserve current primary-graph identities in citation reads

The citation reader in
[`publish_kg_meta_ontology.py`](../../scripts/ops/legal_ir/publish_kg_meta_ontology.py)
consumes graph records for the existing entity stitch. Its name is historical:
the current command reads citations and refuses to publish or replace the
protected graph index. This change supplies no repaired Hub release.

## The actual mismatch and baseline

The historical publisher at datasets commit `5cc320f4a` extracted node identities
from `node_cid`/`id` and endpoints from `src`/`source` and `dst`/`target`.
The current release encoder transports the wrapper fields `entry_cid`,
`legal_id`, `family`, `record_sha256` and `record_json`. Current node bodies use
`entry_cid`; edge bodies use `entry_cid`, `source_entry_cid` and
`target_entry_cid`. Reading only the older names silently loses those values.
The current citation reader inherited that field mismatch.

The independent unpatched control is retained in the workspace artifact directory
`artifacts/legal-ir-graph-citations-20261015/baseline-v01`. At datasets HEAD
`6deae26e98452669b32b256794b18affb1155c16`, one intended regression failed,
with zero errors/skips and unchanged listed inputs. It uses the existing release
encoder to write real private Parquet files, then invokes the real citation
reader. The two authored nodes deliberately share a display label while their
entry identities and legal IDs remain distinct. This is an integration control,
not a real-law interpretation or production-cache repair.

## Reuse validation without inventing physical custody

The existing
[`legal_primary_graph_records`](../../ipfs_datasets_py/logic/autoformal/legal_primary_graph_records.py)
owner defines current wrapped-record validation. Its `decode_primary_graph_payload` validation
checks original `record_json` bytes/hash, bounded finite JSON, wrapper/body
family and identity parity, explicit current identities, and conflicting aliases.
It preserves the original parsed body and unresolved issues. Payload agreement
alone does not authenticate a file, a source revision or an endpoint population.

The full `decode_primary_graph_record` operation still requires independently
expected raw-row and physical-custody hashes. Its manifest, file, row-group and
ordinal declarations remain mandatory. A reader must not manufacture those
inputs merely to reuse a parser. Source files and population coverage remain the
responsibility of the existing manifest and reconstruction owners.

Current entry CIDs are not interchangeable with alternative `node_cid`/`edge_cid`
records, candidate-graph node `record_cid` values, payload CIDs or display labels.
The citation reader uses an explicit current-wrapper path rather than a chain
of permissive alias fallbacks. Current endpoints must close against unique,
compatible current node identities before deriving legal citation IDs. Malformed,
conflicting or missing current bindings refuse instead of producing a plausible
partial citation graph. Explicit unresolved-citation dispositions stay unresolved.
Legacy flat-table compatibility remains a separate path under its existing
contract; it does not gain current-wrapper custody or complete graph authority.
The reader converts current Arrow rows in batches of at most 128 rather than
copying every wrapper into Python at once. The caller's Arrow table, identity
maps, compact edge tuples and returned citation list still scale with population.

## Historical malformed export remains separate work

The retained full pilot census reports **1,960,876 mixed legacy-index rows**,
including **1,722,395 edge rows with both endpoints missing** and **119,134 node
rows missing identity**. The source is the retained
`artifacts/legal-corpus-graph-readiness-20261015-01/pilot-retained-artifact-readiness-v01.json`;
this phase does not repeat that full census. The later pinned Hub footer survey's
1,597,955 endpointless-edge count is a lower bound from complete row groups,
not a contradictory exact total.

The historical publisher above emitted a ten-field `kg-meta-ontology` table.
The observed twelve-field `kg-logic-index` also includes `logical_relation` and
`classification_rule` fields;
its exact final producer lineage is unproven. The mismatch demonstrates a loss
mechanism but does not establish a row-by-row historical reconstruction.
Changing a reader cannot recover bytes already omitted from the old export.

A separate manifest-selected primary reconstruction retains 119,134 nodes and
178,691 edges with checked endpoint integrity at US Code revision `5016b86a…`.
It is useful recovery input. Its 178,691 edges must not be called a complete
repair of the legacy 1,722,395 edge occurrences without independently proven
lineage, multiplicity and source correspondence. Reuse the existing manifest,
record decoder and bounded reconstruction owners for an additive corrected
generation; preserve the old export and unresolved rows rather than guessing IDs.

## Source sampling and the next semantic gates

The source sampler contribution `c5149abeac4c4f5f735125c190d324efe19ab7c4`
contains exactly three files: `legal_source_sampling.py`, its focused test module
and [its guide](legal_source_sampling.md). It reuses the official V2 markup view
and source owners to retain complete block/paragraph custody, exact character
and UTF8 coordinates, and open context requirements. It is useful input
preparation, not legal gold or an entity-endpoint repair. Its training/evaluation
gold masks stay zero; meanings and graph assertions remain absent. Preserve its
concurrent source work and extend its existing owner when the pilot needs it.

Citation identity, local payload integrity, manifest-selected population custody,
reviewed statutory meaning and native Lean consequences are separate gates.
Neither this reader change nor the sampler grants semantic, training, proof,
execution, completion or admission authority. No model weights, embeddings,
8D/384D/768D decoder state or existing cache rows are changed by the reader fix.

The [qualified receipt](evidence/legal-ir-graph-citations-20261015/qualification-v02/receipt.json)
records **406 unique cases**, zero failures/errors/skips and unchanged listed
source/test inputs during execution. These include 38 citation cases, 45
physical/payload decoder cases, 29 sampler cases, and the existing manifest,
reconstruction, entity ingestion/cache, ontology, law-package and producer
packaging/security suites. The [baseline receipt](evidence/legal-ir-graph-citations-20261015/baseline-v01/receipt.json)
records exactly one intended failure before runtime edits. Its frozen regression
and raw JUnit/logs remain separate from the passing result.

The sampler's three files are byte-for-byte copies of the parallel contribution,
integrated with its original author/message in commit `4c9e20741`; the original
checkout is preserved. Qualification uses authored fixtures and private files,
not a full production-cache reconstruction or new model evaluation.
The final qualification includes main's concurrent storage-allocation change
`fc8d69444`; its four paths are preserved exactly. The prior passing composition
is retained as `qualification-v01`, with identical listed source/test inputs.
