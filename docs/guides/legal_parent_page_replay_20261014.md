# Bounded original-parent replay for legal cache observations

The page replay stage qualifies selected original source rows before source-bound
legal spans are reconstructed. It supplies physical custody evidence, not legal
meaning, historical model execution, training gold, official edition
correspondence, or Lean4 proof admission.

The original `legal_producer_lineage` API still selects its conservative v1
row-group decoder. Its entire previously qualified twenty-row report reproduces
exactly, including all twenty unresolved chains and the oversized-group refusal.
The new API and reports use separate pagewise profiles and identities. Completed
source-view and supervisor campaigns remain unchanged.

`legal_parent_parquet_pages` reads the plaintext Parquet footer and every column
page header under fixed lower-only limits. It checks full original-file SHA256
and byte count, descriptor hash, source schema, physical row-group geometry,
column paths and ranges, compressed/uncompressed totals including headers,
dictionary ordering, page counts, encodings, and optional page CRCs. Unsupported
encodings, compression, logical types, encryption, external chunks, or surplus
file bytes are refused.

The supported decoder handles version-1 data pages, PLAIN and RLE_DICTIONARY
values, RLE definition/repetition levels, optional UTF8/INT64/Null primitives,
and optional three-level string/null lists. SNAPPY blocks are decoded directly
with their embedded output length checked before allocation; UNCOMPRESSED pages
are also supported. Compact-Thrift metadata and hybrid RLE cardinalities have
independent depth, node, byte, and value limits. An Arrow row-group reader is not
used to decode the parent rows.

The reader processes one column at a time and retains only the requested physical
rows, preserving every source column. List continuation across pages preserves
null lists, empty lists, null elements, and repeated values. Dictionary expansion
is charged against exact canonical JSON byte budgets before UTF8 copying or list
append. Per-page compressed data is bounded at 16 MiB and decoded data at 32 MiB;
dictionaries at 16 MiB; retained rows at 8 MiB each and 32 MiB in aggregate; and
total decoded pages at 256 MiB. These parser contracts are not kernel quotas or
claims about an absolute process memory peak.

`preflight_parent_pages` returns a complete page-header report. Its full canonical
hash, including its internal seal, is supplied independently to
`read_selected_parent_rows`, along with the original descriptor and the ordered
row ordinals and full-row SHA256 hashes. The selected-row reader regenerates the
page preflight from the same file before decoding. `validate_selected_parent_rows`
regenerates the complete selected-row report, including page witnesses. Self-seals
alone never authenticate a report or authorize changed source inputs.

`legal_producer_page_lineage` accepts a closed, ordered population of independently
pinned page and selected-row reports. A fixed owner regenerates each parent
inventory using the original witness manifest and exact requested row hashes.
Callers cannot provide a substitute reader or inject projected rows. Shared
declaration checks validate all physical cache records and their exact producer
receipt pointers without changing the public v1 profile. The new v2 report keeps
all records and ambiguities, has a distinct schema/seal, and leaves every legal,
historical execution, training, and proof authority flag false.

The actual parent is `justicedao/ipfs_uscode` revision
`5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`, path
`uscode_parquet/laws.parquet`, SHA256
`4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8`.
Its 374,277,662-byte file contains 60,077 rows and 45 leaf columns in one group.
That group's 1,170,039,502 declared decoded bytes remain outside the v1 profile.
The new preflight inventories all 423 page headers. Selected rows 2673, 2674,
2675, 2676, 2677, and 2681 retain all 45 source fields and exactly match the six
independent full-row hashes. They occupy 103,137 canonical JSON bytes. The read
uses 90 page bodies totaling 60,389,242 decoded bytes; it does not assemble or
qualify every parent row.

Across the same twenty physical cache records, eight have verified local
producer-report/parent declarations and twelve remain unresolved. Eight unresolved
records match authored demonstration projections, and four flat records lack a
producer report pointer. No original character occurrence is selected and no
governing source binding is accepted. The earlier unqualified parent reads and
all failed qualification artifacts remain preserved as separate evidence.

Upstream training has advanced again. The actor-context feature experiment,
completed on 2026-10-14 and integrated through PR1299, combines masked source-token
attention with a copied actor head. Its 32 updates trained 258 active scalars
while retaining 34 frozen base tensors. Recorded independent primary recounts
show no complete-IR gain or loss against either CE-only or hinge-trained controls
in nine authored panels. Training stays at 153/168; fresh development and test
stay at 0/36 each. Lower training actor rank sum, 205 versus 206 for CE, does not
establish a legal accuracy gain; fresh development rank sum worsens from 312 to
314. Six frozen modality errors and two other optional-presence errors motivate
the next controlled experiment. All scored panels were previously exposed
engineering references, and eight statutory examples remain unscored.

The additive experimental archive is `Publicus/legal-ir-autoencoder`, revision
`f91692a0a695d91b793a00936dd525fbe2bafcac`, under
`releases/20261013-actor-features-v1`. The campaign checks public metadata and
recorded primary results without reading checkpoint weights or running training
or inference. Actor-feature adaptation is now a completed experiment, not an
unrun proposal. Default model promotion, genuine latent semantics, legal gold,
and Lean4 admission remain unqualified.

The three native supervisor jobs qualify page preflight, selected-row replay, and
full producer page lineage plus detached actor-feature contracts. They use the
existing shared resource ledger, unchanged resource policy and native proposal
limits, sealed venv imports, fixed source pins, lossless bounded receipts, and
same-generation terminal fencing. The page suite runs in both reader lanes;
distinct-test reporting counts those cases once. Independent replay follows
native merge and lease release. The original sixty-task plan remains partially
accepted.

Next, reconstruct candidate statutory spans from the verified parent text with
explicit character offsets and all literal occurrences retained. Separate metadata,
notes, headings, and statutory body observations; do not choose an occurrence or
legal role from uniqueness alone. Authenticate source/context correspondence and
record independently reviewed modality, actors, definitions, references,
exceptions, quantifiers, and temporal scope. Only reviewed source-bound spans can
feed typed entity/definition/relationship proposals, conflict-preserving doctrine
composition, and separately checked Lean4 statements and proofs.

The parser follows the primary
[Parquet format](https://github.com/apache/parquet-format/blob/master/src/main/thrift/parquet.thrift),
[encoding specification](https://github.com/apache/parquet-format/blob/master/Encodings.md),
[Thrift compact protocol](https://github.com/apache/thrift/blob/master/doc/specs/thrift-compact-protocol.md),
and [Snappy format](https://github.com/google/snappy/blob/main/format_description.txt).
