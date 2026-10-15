# Current entity-cache census and repair boundary

The pinned [entity-cache file](https://huggingface.co/datasets/justicedao/uscode-autoformal-entity-cache/blob/79d54378c5d6a89ab56e7a27e0f0ba867e800e19/autoformal/uscode/kg-logic-index.parquet)
still cannot supply a connected graph for LegalIR training or the Lean corpus.
The complete census accounts for **1,960,876 mixed records**: every one of its
**1,722,395 edge observations fails both endpoint lookups**, and **119,134 node
observations lack an identity**. This is an exact population check on the current
file, not an extrapolation from the historical export or the unversioned Viewer.

The run downloaded the file only after native admission, verified its exact
11,139,328 bytes and SHA256
`f5f07379d4ca913cb2d8d98505a4ecb01e4d0658039a2f4ff84fb4fb585e8233`,
then reused the unchanged
[`legal_entity_index_intake.census_parquet`](../../ipfs_datasets_py/logic/autoformal/legal_entity_index_intake.py).
The frozen source checkout was `832c9d3b28f68c55237c4af2e99dd9ec5c137db5`.
No decoder fit, model upload, source-meaning review or Lean build occurred.

## Complete population and limits

The [footer report](evidence/legal-entity-cache-audit-20261015/footer-population.json)
records 99 row groups, the exact twelve-field string/Boolean schema and
1,960,876 rows. This observed footer supplied the census's expected row count
after independent byte/hash verification. It was not an independently known
source-corpus denominator. The [complete census](evidence/legal-entity-cache-audit-20261015/entity-index-census.json)
preserves all record kinds and exclusive dispositions:

| Disposition | Rows |
| --- | ---: |
| Node with a declared nonempty identity | 119,318 |
| Node missing identity | 119,134 |
| Edge with unresolved endpoint(s) | 1,722,395 |
| Edge with ambiguous declared endpoints | 0 |
| Edge with uniquely resolved declared endpoints | 0 |
| Category observation | 9 |
| Logical-relation observation | 6 |
| Classification-rule observation | 14 |
| **Total** | **1,960,876** |

Both the source-missing and target-missing edge counters equal the entire edge
population. Thus every edge fails both lookups. The owner's missing-endpoint
counter includes empty/null values and nonempty dangling identifiers; it does
not separately count those causes. Global empty `src`/`dst` counters also include
non-edge observations and cannot establish the number of blank edge endpoints.
The six logical-relation rows are metadata, not recovered graph edges.

There are zero duplicate nonempty node identities. Six duplicate raw-row groups
contain **1,722,389 extra instances**, leaving 238,487 distinct canonical raw
rows. This does not justify deleting duplicate occurrences: lost endpoints may
have collapsed distinct original edges into identical projections. The census
does not recover original multiplicity or distinguish duplicate-group payload
lineage. Equal labels, legal IDs or hash prefixes cannot supply missing identity.

All 1,960,876 observed `admitted` and `formalized` booleans are false. The
24,389 `in_formula=true` observations remain legacy producer flags. All census
authority flags are false, including source binding, semantic review, training,
graph assertion generation and proof authority. Ontology mapping agreement does
not establish legal interpretation or executable logic-family support.

The current file differs from the earlier 16,898,459-byte/16-group snapshot.
Matching row totals do not prove equal rows or repaired lineage. The new census
establishes the current file's defects without inheriting the old generation's
payload conclusions. Neither file establishes complete statutory coverage.

## Qualification and resource closeout

The [frozen request](evidence/legal-entity-cache-audit-20261015/validation-request-v01.json)
binds 18 sources and the [input descriptor](evidence/legal-entity-cache-audit-20261015/input-descriptor-v01.json).
The native request reserved 512 MiB storage, 2 GiB memory, one CPU slot and one
child process slot, with a 900-second deadline. It used the existing ledger,
scheduler policy, startup barrier and validation launcher. No policy or capacity
limit changed, and no foreign artifacts or claims were released.

The [child receipt](evidence/legal-entity-cache-audit-20261015/entity-cache-audit.json)
records all four selected checks passing in 34.80 seconds: verified acquisition,
pinned footer population, one complete census and input-refusal controls. The
[two controls](evidence/legal-entity-cache-audit-20261015/input-refusal-controls.json)
reject a wrong file SHA and a wrong expected row count before row traversal.
They do not repeat the full census or treat a self-derived report hash as an
independent prior binding.

The parent [execution](evidence/legal-entity-cache-audit-20261015/execution.json)
and [result](evidence/legal-entity-cache-audit-20261015/result.json) record exit 0
and completion. The [durability inventory](evidence/legal-entity-cache-audit-20261015/validation-durability.json)
binds the retained source and every produced output after the group was observed
stopped. Actual parent terminal output reported the storage claim and native
lease released, with no cleanup error. The published
[closeout projection](evidence/legal-entity-cache-audit-20261015/native-parent-closeout-observation.json)
is explicitly transcribed from that terminal output; it is not a byte-identical
stdout capture or independent live-ledger authentication. Final retained attempt
size was 11,183,687 bytes. Resource supervision remains cooperative and sampled,
not a kernel quota.

The helper compiled six product modules from checked source buffers, refused
unexpected product/model/SDK/CID imports, and rechecked source and input custody.
PyArrow 23.0.1 and NumPy 1.26.4 were imported inside native execution; recorded
versions do not authenticate installed distributions. The separate static review
executed no product or numerical code. These four checks and two refusal controls
are not additional pytest counts or semantic-quality scores.

The [independent metadata recount](evidence/legal-entity-cache-audit-20261015/independent-metadata-review.json)
recomputes the canonical census hash and population sums without reopening the
Parquet. It checks derived-file commitments, exact source origins, refusal records
and the recorded closeout, with the same release-projection limitation.

Before publication, main advanced to `060996f1cbca2bc34193e97ec38736ca0064c3b5`.
Its four CUDA source-coordination paths were fast-forwarded unchanged. The
[reconciliation](evidence/legal-entity-cache-audit-20261015/upstream-reconciliation.json)
confirms all 18 audit pins, including 16 repository sources, remain exact. This
does not claim execution of the incoming contribution.

The [publication manifest](evidence/legal-entity-cache-audit-20261015/publication-manifest.json)
binds exact copies of selected metadata and derived evidence. The original
Parquet remains in the owned native export directory and at its immutable Hub
revision; no Parquet payload is added to Git. Published absolute-path requests
and the campaign helper are retained evidence, not portable grants. A rerun needs
a newly frozen request and fresh native admission. Canonical census/stream hashes
include the original absolute input path and change on relocation.

## Next repair and semantic work

Follow-up: the [primary-graph candidate exporter](legal_primary_graph_export.md)
now implements the bounded adapter and original-bound readback below, qualified
by 160 distinct authored-fixture cases. Actual original-corpus generation and
historical flat-cache occurrence/multiplicity reconciliation remain pending.
Its new-generation lineage describes selected primary occurrences; it does not
establish the missing historical original-to-flat mapping.

1. Reuse `legal_primary_graph_manifest` to select and verify the exact original
   files and physical rows, `legal_primary_graph_records` to decode their explicit
   identity profile, and `legal_primary_graph_reconstruction.reconstruct_to_jsonl`
   for complete observation retention, duplicate/conflict checks and endpoint
   closure. The separately retained 119,134-node/178,691-edge reconstruction is
   selected structural evidence; it is not a row-for-row repair of these
   1,722,395 legacy edge occurrences.
2. Run the qualified candidate exporter over those independently frozen verified
   originals, preserving full bodies and exact occurrence/source commitments.
   Separately establish a lineage ledger mapping each historical occurrence to
   supported original evidence or an explicit unresolved disposition. Keep flat `node_id`,
   current `entry_cid`, alternative `node_cid` and semantic candidate-node record
   CID namespaces explicit. Do not infer correspondence from labels.
3. Reuse the actual `uscode_hf_release._encode_parquet_rows` writer and the existing
   `test_current_wrapped_graph_parquet_preserves_exact_citation_identity` regression.
   That regression preserves two same-label nodes, one typed edge, complete
   bodies, hashes and role/ordinal/source fields through real Parquet readback.
   Apply the qualified readback guards to the actual generation and require full-population
   identity, endpoint, multiplicity and source reconciliation after readback.
   Writer success alone does not establish global closure. The current
   `publish_kg_meta_ontology.py` is a citation reader and intentionally cannot
   publish a replacement index.
4. Continue the [reviewed statutory component](pilots/uscode_definition_component/README.md)
   using the already qualified source-binding/review owners. Actual independent
   definition, complete-norm and per-use governing-scope decisions remain absent.
   Structural repair can proceed in parallel; semantic graph admission, new
   statutory training targets and the actual `lake build legal` still require
   their separate meaning, representation and proof gates.

The [comprehensive plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
retains the independent 8D/384D/768D experiment lanes. This census changes their
input-readiness evidence, not their weights, measured accuracy or promotion state.
