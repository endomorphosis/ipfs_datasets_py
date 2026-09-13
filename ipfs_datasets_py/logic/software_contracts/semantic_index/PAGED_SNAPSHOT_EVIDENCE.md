# Closed, paged committed metadata

`page_snapshot_evidence` pages the existing complete committed snapshot entry
records and retains their original entry and snapshot CIDs. It creates a new
metadata root linking bounded entry pages and the independently admitted chunk
manifest root. The ordinary snapshot classes, schemas and scanner are unchanged.

Every page has a starting ordinal and a nonempty record list. The root records
entry count, original snapshot header/CID, page references and explicit byte
bounds. `PagedSnapshotEvidence.artifact()` produces a small snapshot-evidence
reference for the explicit chunk consumer. A complete 15,770-entry synthetic
population is tested without acquiring a live repository's contents.

`parse_paged_snapshot_evidence` checks closed schemas, canonical bytes and CIDs,
all page references, ordinals, counts, strict raw-path ordering, every original
entry CID, and the reconstructed original snapshot CID. Rebuilding the canonical
page layout detects alternate or substituted representations. Missing, duplicate,
reordered or unreachable pages/entries are refused. The returned snapshot has
no captured bytes and remains a metadata claim.

`parse_chunked_snapshot_manifest` closes the previously write-only chunk DAG.
It checks every structural block/reference, closed schema, declared and qualified
budget, exact inventory/count/order, Git object mode/size, chunk offset/extent,
raw content CID format, and the complete population CID. Every structural block
must be reachable, and the canonical reconstructed root must match the expected
root. Both parsers seal input byte mappings and enforce the 1 MiB frame ceiling
and a bounded aggregate metadata size. Before JSON decoding, fixed CID widths,
nonempty frames and population-derived block counts also bound mapping overhead.

`admit_chunked_snapshot_manifest` additionally compares the parsed inventory
with a fresh exact Git metadata preflight at the requested repository/HEAD/tree.
This establishes the committed scope of the references. It does not establish
that a declared raw source/chunk CID matches the blob contents. The existing
`project_chunked_repository` must still read and hash every immutable blob before
positive use. A test supplies a self-consistent but false source-CID claim:
metadata admission succeeds, and content projection refuses it.

The caller must supply trusted expected root and population identities, plus
qualified admission limits. Raw blob/chunk content is not included in the
metadata DAG. The paged snapshot's source-manifest reference names the separate
chunk DAG; the explicit consumer admits both DAGs and persists both in its
returned bundle. Neither parser issues semantic or completion acceptance.

Paging reduces serialized block size. Reconstructing an original snapshot CID
still processes its bounded full metadata in memory, and the current scanner
still retains ordinary source bytes. Large ordinary-source populations require
a streaming scanner/pytest frontend. Other large semantic-state indices or AST
blocks may also require paging before they can pass a fixed frame ceiling.
