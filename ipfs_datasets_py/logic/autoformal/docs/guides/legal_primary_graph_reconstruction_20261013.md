# Manifest-selected primary legal graph reconstruction

This additive path reconstructs a separate candidate graph transport from the
release manifest of `justicedao/ipfs_uscode`. It preserves the published
`kg-logic-index.parquet` and every cached historical shard. It does not repair
identifiers by guessing from labels, legal IDs, row positions or ontology terms.

The pinned release at revision `5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`
selects 30 wrapped node shards and 44 wrapped edge shards: 119,134 nodes and
178,691 edges. The same cached snapshot retains 407 older graph shards outside
that selection. The prior materialized-index census counted 119,134 nodes without
IDs and 1,722,395 unresolved edges. Matching counts support investigation; they
do not establish exact row lineage or identify the published index's producer.

## Manifest and immutable file custody

`legal_primary_graph_manifest.select_primary_graph_manifest` consumes raw manifest
bytes and independently supplied raw SHA256, repository/revision, expected release
identity and complete expected graph population. It selects the exact descriptor
membership and verifies the producer's internal manifest digest. A declared
release CID remains a declared identifier unless separately verified.

`verify_primary_graph_files` checks every selected body hash, byte count, exact
wrapped Arrow schema and footer row population. Finite decoded/batch/file/row
limits apply. Historical extras stay separate and supply no selected records.
`iter_verified_graph_rows` traverses only selected descriptors, with guarded file
descriptors, bounded batches and stable file identities. Exhaust the iterator for
its complete traversal checks; an individual yielded record cannot attest full
population coverage.

Ordinary input paths cannot escape the selected root. An explicit `blobs_root`
permits Hugging Face's cached snapshot links only within the same repository's
blob store. Arbitrary links and changed files are refused. Cached blob names
alone never establish body integrity.

## Original record identities

`legal_primary_graph_records.decode_primary_graph_record` retains the exact raw
five-column wrapped row and original JSON string. It verifies strict JSON,
`record_sha256`, wrapper/body family and entry identity parity, and independent
raw-row/custody pins. Unknown body fields remain intact. The producer's empty
wrapper legal ID can represent an absent or null optional body legal ID; the
decoder does not invent one.

Current nodes use their literal `entry_cid`. Current edges use their own literal
`entry_cid` and explicit `source_entry_cid`/`target_entry_cid`. Legacy `node_cid`,
`edge_cid`, `src` and `dst` do not become implicit aliases. Conflicts, unsupported
versions or absent identities remain named gaps or refusals. Labels never merge
entities or reconstruct an endpoint.

## Complete candidate reconstruction

`legal_primary_graph_reconstruction.reconstruct_to_jsonl` takes the independently
pinned selection, snapshot root and a new output path. Bounded SQLite scratch
storage accounts for every physical row, declared identity and complete endpoint
population. The candidate retains ordered record-level source lineage and binds
the complete selection and verified source files. Original raw records remain in
the unchanged, body-verified shards and can be replayed through the decoder.

Candidate output is deterministic across output locations. Its report binds the
exact output byte count/hash and complete node/edge dispositions, including
duplicate/conflicting identities and missing or ambiguous endpoints. Output and
scratch bounds fail without publishing a partial candidate. Existing output
files are never overwritten.

The candidate's selected-file header excludes local cache paths and unselected
historical inventory. Moving identical selected bytes to another cache location
or retaining additional historical files leaves candidate content unchanged.
Excluded-file observations remain in the separate complete verification report.

`validate_reconstruction` rebuilds the complete candidate in owned temporary
storage from independently trusted source inputs, then compares the report and
candidate evidence. An incoming report's own digest cannot replace independent
source or selection pins. Run complete scans only under the supervisor's shared
validation resource lease.

## Interpretation and admission

Declared endpoint integrity concerns only this exact selected graph population.
Its source-package, structural, citation or other graph labels remain producer
declarations. Transport validity does not establish legal meaning, statutory
completeness, governing definitions, applicability or global legal consistency.
Every semantic, admission, training and proof authority flag remains false.

The additive [navigation bundle](../../../../../docs/guides/legal_primary_graph_navigation_20261015.md)
projects a complete conflict-free reconstruction into the existing twelve-field
index schema while retaining this entire candidate as its companion. Its
validator repeats source reconstruction and checks every projected row; it does
not replace this owner or grant semantic admission.

The complete pinned run observed 119,134 unique node IDs and 178,691 unique edge
IDs, without duplicate/conflicting identities or missing/ambiguous endpoints.
Producer labels include 59,520 section nodes, 59,520 source-package nodes,
55 title nodes and 13 unresolved-citation nodes. There are 13 `CITES_UNRESOLVED`
edges. A reference to a placeholder node satisfies declared endpoint presence;
it does not resolve that citation or establish a source-grounded legal assertion.
Declared descriptor first/last key ranges and the release root CID are retained
without claiming that those fields were independently recomputed.

Source-bound canonical assertions still require exact official source occurrences,
document edition/scope identities, explicit ASTs and governing context through
the existing proposed-graph APIs. Actual authenticated independent legal/formal
review and current complete dependencies precede accepted views. Doctrine
composition and Lean 4 module admission remain downstream checks.

Three native deterministic jobs qualify file custody, record decoding and complete
candidate reconstruction. Separately pinned full-input reports supplement
adversarial fixtures. Native execution and post-merge independent replay rebuild
the same complete populations. No model inference, training, corpus publication
or toolchain download occurs in this phase.

The source-contract population is 47 manifest/file cases, 40 record-decoder cases
and 27 reconstruction cases, plus 21 supervisor-driver checks. A real full-input
prequalification exposed a quadratic identity lookup; an indexed lookup and a
populated SQLite execution-budget regression now cover that path. The stopped
attempt and its incomplete output remain separate failure evidence.
