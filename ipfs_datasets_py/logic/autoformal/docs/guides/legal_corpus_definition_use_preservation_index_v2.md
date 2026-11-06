# Observational indexing of retained V2 corpus packets

The [index adapter](../../legal_corpus_definition_use_preservation_index_v2.py)
projects the supported [retained corpus packet](legal_corpus_definition_use_preservation_packet_v2.md)
into the existing unified store. The stored result is explicitly `UNKNOWN`,
with `CANDIDATE` result authority, `NONE` evidence authority and trust, and
negative cache polarity. Retrievable observations provide no proof, source,
legal, review, training or compiler-reuse authority.

The existing [DuckDBProofStore](../../../common/duckdb_proof_store.py)
now persists its existing normalized catalog when supplied an explicit DuckDB
connection. A store without a connection retains its original process-local
behavior. Passing a connection previously installed tables without persisting
entries; the new path performs actual SQL writes and cold readback.

**Qualified on October 15, 2026:** all 153 tests passed without failures, errors
or skips: 47 real SQL persistence cases, 47 packet-index cases and 59 existing
store regressions. Separate owned DuckDB 1.5.5 integration wrote both previously
compiled authored FOL/TDFOL packet observations and recovered both after database
close/reopen, preserving all thirty normalized key dimensions. Independent
readback verified all 123 exports, the unchanged 110 prior exports and the
closed database file. No new Lean invocation, compiler probe or legal proof-cache
write occurred. The
[qualification receipt](../../../../../docs/autoformalization/evidence/legal-ir-preservation-publication-20261023.json)
binds exact sources, requests and evidence. Unit packet claims remain explicitly
synthetic; actual integration consumes the earlier qualified native packets.

## Preparation, writes and retrieval

`prepare_definition_use_preservation_index_v2` takes the original immutable
49-file byte packet, original typed corpus preparation, assessment and complete
packet-reader arguments. It also requires an independently trusted SHA256 of
the exact packet-observation bytes and an explicit `created_at` timestamp. It
calls the qualified packet reader itself; a publicly constructed packet-result
dataclass cannot substitute for complete current source/review replay.

The adapter bounds and commits the complete argument tree before replay, then
checks the same type-sensitive commitment immediately afterward and at return.
Bytes, booleans, integers, floats and null have distinct commitments. This also
detects mutation just after a successful reader returns.

The returned `RetainedCorpusIndexProjection` has sealed `projection_json` and
an immutable typed `UnifiedProofEntry`. Its exact-byte envelope points to the
packet observation. Separate unreviewed runtime evidence points to the original
native receipt bytes; the receipt payload's record CID remains separate. The
adapter does not relabel these engineering records as a legal-domain
`FormalizationArtifact` or theorem `ProofReceipt`.

`write_definition_use_preservation_index_v2` prepares the projection, requires
an explicit `STORED` acknowledgment, checks its projected protocol entry, reads
back the full unified entry and replays the original packet again before
issuing a successful operation receipt. Backend exceptions and inconsistent
acknowledgments remain visible. A failed post-write replay may leave an
observational row; it does not produce a successful operation receipt. Source
replay and backend storage do not form one distributed transaction.

`lookup_definition_use_preservation_index_v2` requires independently expected
full key and entry digests. It repeats current packet replay before lookup,
checks candidate/no-trust ceilings and an exact negative hit, reads back the
complete entry, and replays again. A genuine missing entry returns `None`.
Expired, incompatible or corrupt hits refuse explicitly. Profile or source
search results cannot replace the complete expected key.

Write and lookup accept a bounded explicit `now` or use current wall time.
Query time must not precede entry creation, and normal store expiration remains
effective. Use the same explicit creation time to reproduce an entry identity.
Creation time is not a semantic-key dimension.

## Complete key dimensions

| Unified key dimension | Bound material |
| --- | --- |
| IR | Complete original/preservation preparation hashes and engineering reference material |
| Property | Exact four role fragments and fifteen theorem identities |
| Assumptions | Original theorem assumptions and unchanged pending/rejected preparation state |
| Selected premises | Complete declared review dependency artifacts |
| Translator | Current producer pins, index/store owner pins and original semantics hash |
| Solver | Historical binary identities, with fresh execution false |
| Toolchain | Exact historical toolchain and sibling compiler hash map |
| Theorem registry | Theorem partitions, expected modules and closed import graph |
| Policy | Complete original argument commitment, assessment, review intake/dependencies and authority state |
| Resources | Complete packet inventory and bounded input/record budgets |
| Tree | Whole packet, raw receipt and raw packet-observation hashes |
| Backend ID/version | Dedicated observational namespace and versioned adapter profile |
| Backend binary | Historical compiler identity map |
| Backend configuration | Index/store owner hashes and explicit UNKNOWN/CANDIDATE/NONE state |

Composite dimensions hash canonical structured values through the existing
unified-key owner. Their normalized digests are not raw file hashes. The
original raw-byte commitments remain available separately.

## Explicit-connection SQL persistence

The caller owns the connection, exclusive access to it, and filesystem/resource
custody. Store operations must start outside a caller transaction. The existing
connection manager can supply a security-hardened trusted broker handle; this
adapter creates no connection, service, remote endpoint or additional owner.

SQL operations use the existing `proof_keys`, `proof_key_dimensions`, `premises`,
`proof_entries` and `proof_evidence` tables. Entry JSON retains the complete typed
entry. Reads check byte lengths before fetching text, require canonical finite
JSON, verify all fifteen normalized dimensions and premise/evidence rows, and
reconstruct full entry and envelope identities. SQL failures and tampering
cannot fall back to a warm memory entry.

Writes replace an existing exact-key entry inside a transaction and commit only
after readback. Failed writes roll back. Invalidation, clearing and expiration
delete persisted rows so reopening cannot resurrect them. Finite capacity uses
creation-time/key ordering. Access counters and single-flight coordination remain
local to the store instance; this work does not make them a distributed service.

Operation receipts keep `durable_storage_verified=false`: an adapter cannot
infer filesystem durability or cold reopen from a generic backend acknowledgment.
A separate owned qualification can verify close/reopen and retained database
bytes. Successful persistence does not change any proof or legal authority.

## Remaining integration boundaries

This profile indexes engineering observations and their complete dependencies.
It does not hydrate a statutory entity graph or vectors, activate DuckLake or
Quack, reuse `.olean` files, or authorize a theorem-specific legal proof cache.
The existing graph dependency owner remains responsible for declared reverse
invalidation. Its legal/source changes must be evaluated before retrieval;
database presence is never a freshness or source-review decision.

Existing graph/source SQL query templates need a separately qualified projection
for the complete entry JSON's `result_payload` paths. They are not established by
exact-key storage and retrieval. Reviewed statutory source correspondence,
broader logic constructors, general translation preservation, measured token
savings and held-out model convergence remain independent gates.

The original official-V2 APIs retain their twelve-module, fifteen-theorem, 49-file preservation contract. The separate [direct parent-norm siblings](#opt-in-direct-parent-norm-preservation-index) accept only their explicit 23-file receipt-consistency profile. Shared/aggregate and direct-incremental packets remain unsupported; schema relabeling or a matching hash cannot substitute for the complete matching replay contract.

## Current primary reconciliation — 153 cases / 459 phases passed

The [closed current-source qualification](../../../../../docs/autoformalization/evidence/legal-ir-preservation-publication-20261023.json)
passed 153 authored-fixture cases / 459 setup, call and teardown phases: 47
real-SQL persistence cases, 47 packet-index cases and 59 store regressions. Packet
execution claims in the unit fixtures remain synthetic. Real SQL writes and
cold close/reopen concern fixture entries, separately from the historical
DuckDB 1.5.5 replay of two compiled FOL/TDFOL packets. The cohort includes one
unchanged exact stdlib cold-index child with its 20-second timeout. A declared
path-only reasoning namespace executes genuine required leaf modules; the
public reasoning package initializer was not executed and remains outside this
qualification. Original native, storage and source READ custody closed.

The original 153-case qualification and separate two-packet cold readback above
retain their original source generation. This fresh fixture integration
qualifies current dependencies without creating another receipt adapter or
promoting old packets to a current replay. UNKNOWN/CANDIDATE/NONE observations
remain nonauthorizing. Parent/shared/direct-incremental packets, theorem-specific
legal proof cache, DuckLake/Quack activation, model/training and Lean admission
remain unsupported or unqualified as before.

At this publication-preparation cutoff, no new test cohort, historical packet/database replay, native or Lean run, or model execution has been performed. The linked portable evidence records the retained 153-case/459-phase primary composition and its declared reasoning namespace profile separately from the original 68-case packet qualification, original 153-case SQL/index qualification and historical two-packet replays. Those qualifications keep their original source/toolchain scopes. Preserved public companion differences do not establish whole-runtime byte identity with the 126 raw-compile observations/119 module origins or qualify the public reasoning initializer/reexports. Original receipts, packet/database exports and raw execution evidence remain unbundled and unavailable in a clean clone; the portable record supplies their immutable descriptors and scope, rather than substituting fresh runtime evidence.

## Opt-in direct parent-norm preservation index

Reuse `prepare_parent_norm_preservation_index_v1`,
`write_parent_norm_preservation_index_v1` and
`lookup_parent_norm_preservation_index_v1` in this same existing owner.
Their projection schema is `legal-corpus-parent-norm-preservation-index-projection/v1`,
operation schema is `legal-corpus-parent-norm-preservation-index-operation/v1`,
and profile is `retained-parent-norm-receipt-consistency-index/v1`.
The original official-V2 APIs and their historical qualifications retain their
separate contracts and source generations.

The new siblings take the original immutable 23-file byte packet, complete
seven-file typed parent preparation, full original correspondence, all nine
original correspondence-replay fields, and independent full preparation,
correspondence, raw receipt, bundle, binary and versioned-toolchain commitments.
They also require an independently trusted SHA256 of the exact current packet
observation and an explicit stable entry creation time:

```python
projection = prepare_parent_norm_preservation_index_v1(
    packet_files, preparation, correspondence,
    expected_packet_observation_sha256=packet_observation_pin,
    created_at=creation_time,
    **packet_arguments,
)
```

`packet_arguments` has exactly `expected_preparation_sha256`,
`expected_correspondence_sha256`, `correspondence_inputs`, `toolchain`,
`expected_receipt_file_sha256`, `expected_bundle_sha256` and
`expected_binary_sha256`. Publicly constructed packet/projection results do not
substitute for genuine original-input replay. Caller-computed hashes are not
independent provenance.

All fifteen existing unified-key dimensions remain present. Their material
retains the complete parent-preparation/correspondence commitments, unchanged
norm, declared theorem assumptions and conditional modules, original parent
context, review intake, unresolved blockers, semantic-coverage declarations,
current producer/index/store pins, historical toolchain/binaries, full packet
inventory and receipt/observation hashes. Context and review-binding values are
retained observations; selecting them as key material supplies no legal premise
or resolved meaning. `created_at` changes the full entry identity and is
custody-fenced, while remaining outside the semantic key.

Every operation retains complete input, callback, owner-path/source, physical
witness and actual typed-entry custody. A changed input after a genuine reader
returns, an integrity-valid mutation of the live stored entry, or final
seal/serialization/result substitution refuses. Writes require the exact stored
acknowledgment and complete typed readback. Hits require independently expected
full key and entry digests. Both hits and genuine misses receive complete closing
packet replay; a genuine miss returns `None`. Exceptions remain visible. A failed
post-write validation may leave an observational row but yields no successful
operation receipt; source replay and the caller's backend are not one transaction.

The stored entry is UNKNOWN with CANDIDATE result authority, NONE evidence
and trust, and negative polarity. `receipt_consistency_only=true`;
`accepted_execution`, `accepted_outer_operation` and
`accepted_operation_result_bound` remain false, and
`outer_operation_outcome="unprovided"`. A consistent retained successful build
receipt does not provide the missing outer closeout. `proof_usable` and
`durable_storage_verified` remain false; training and evaluation-gold masks
remain integer zero.

This profile's authored-fixture qualification uses synthetic retained compiler,
runtime and artifact claims, genuine current original-parent preparation and
physical-source replay, and the genuine process-local store. It supplies no new
SQL or cold-reopen qualification, actual historical native-packet replay, native
compiler/Lean/model execution or training. Existing SQL, packet and native
campaigns remain separately attributed. Source/edition/meaning, reviewed
eligibility, graph/corpus admission and legal proof-cache authority remain open.

The [accepted two-operation index qualification](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-preservation-index-20261025.json) retains 114 passed original pytest cases / 342 phases (68 new index controls plus 46 selected official-V2 index regressions). Pytest returned0, but the original wrapper returned1 because its terminal audit required37 sources, including two unused prior-native requirements. A separately owned metadata-only audit verified the corrected35-source closure and all162 raw checked source buffers. It executed0 new product tests. The original wrapper remains failed; neither it nor the earlier timeout receives retroactive credit. The new source-audit-reconciled qualification keeps both original case and new audit execution identities, rather than relabeling the original controller. Original packet/native/SQL campaigns retain their separate scopes; masks stay zero. The final denied-module-absence assertion was not run and is not reconstructed; full final third-party module closure remains unprovided. Ordinary342-phase completion with pytest returncode0 does not establish the unenrolled strict physical-fixture-v2 finalizer contract. Recorded blocked-import/operation observations and the zero model/Lean counter concern the enrolled tested operations, without host/startup, third-party bytecode, kernel or whole-package attestation.

## Compatibility metadata index projection

`project_lean_compatibility_index_v1` projects the packet owner's bounded compatibility request into a deterministic metadata key. It preserves ordered route/digest selections, artifact closure and unresolved questions without opening a store or invoking a compiler. `lean_compatibility_index_sha256` pins the complete projection; `validate_lean_compatibility_index_v1` requires an independent projection SHA256 and complete regeneration. Each result is detached from earlier calls.

The caller-selected AST digests remain opaque commitments. All admission fields remain false, and this projection is separate from the existing physical packet/index read and write operations. Reuse the [packet preparation contract](legal_corpus_definition_use_preservation_packet_v2.md#compatibility-preparation-without-native-execution) and its separate 28-case focused qualification; it does not transfer historical native, legal, graph/corpus or proof-cache authority.
