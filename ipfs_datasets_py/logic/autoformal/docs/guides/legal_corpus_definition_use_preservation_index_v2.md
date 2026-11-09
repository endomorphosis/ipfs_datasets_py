# Observational indexing of retained V2 corpus packets

The [index adapter](../../legal_corpus_definition_use_preservation_index_v2.py)
projects the supported [retained corpus packet](legal_corpus_definition_use_preservation_packet_v2.md)
into the existing unified store. The stored result is explicitly `UNKNOWN`,
with `CANDIDATE` result authority, `NONE` evidence authority and trust, and
negative cache polarity. Retrievable observations provide no proof, source,
legal, review, training or compiler-reuse authority.

The original official-V2 APIs retain their twelve-module, fifteen-theorem, 49-file preservation contract. The separate [direct parent-norm siblings](#opt-in-direct-parent-norm-preservation-index) and [parent-bound norm/definition siblings](#opt-in-parent-bound-normdefinition-index) have explicit 23-file and 29-file receipt-consistency profiles below. Shared/aggregate and direct-incremental packets remain unsupported; schema relabeling or a matching hash cannot substitute for the complete matching replay contract.

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
[qualification receipt](../../../../../../../artifacts/legal-ir-corpus-index-20261015-01/qualification-receipt.json)
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

## Current primary reconciliation — 153 cases / 459 phases passed

The [closed current-source qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-preservation-index-primary-integration-20261022-01/qualification-summary-01.json)
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

## Source publication closeout, 2026-10-23

**Preservation publication closed, 2026-10-23:** [datasets PR #1356](https://github.com/endomorphosis/ipfs_datasets_py/pull/1356) merged as `6477402ca03d4efb61448fe5ce5354cdf1f29442`; [parent PR #602](https://github.com/endomorphosis/lift_coding/pull/602) adopts it at `07fd77aff8248adf952cc08879b9c9f36aa43389`. The [source-generation review](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-preservation-publication-20261023-01/source-qualification-reuse-review-v01.json) and [public dependency review](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-preservation-publication-20261023-01/independent-public-dependency-review-v01.json) retain their earlier conditional-cutoff records; the later [joint selection](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-preservation-publication-20261023-01/selected-publication-v03.json) and [publication closeout](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-preservation-publication-20261023-01/publication-closeout-v01.json) resolve this source-publication boundary without rewriting those receipts. The dependency-complete source bundle contains eleven source/test paths, including existing preservation ancestors and the qualified SQL store successor; its eight changed store method bodies preserve all 77 original signatures. The 153-case/459-phase primary composition remains 47 SQL, 47 index and 59 store controls in its declared namespace, separate from historical 68 packet controls, original 153-case SQL controls and ancestor 200/301-case campaigns. Actual retained-packet, native and database observations remain historical; no new test, SQL/database replay, model, training, compiler or Lean execution is performed for publication. These primary guides retain their full original prefixes. Support remains the official V2 twelve-module/fifteen-theorem/49-file observational profile; parent/shared/direct-incremental packets remain unsupported. Stored UNKNOWN/CANDIDATE/NONE negative-cache observations supply no proof usability, source/meaning/review, training/gold, graph or Lean admission. Raw local artifacts are unbundled and hosted CI success is not claimed.

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

## Opt-in parent-bound norm/definition index

The opt-in extension reuses this index owner and the
[29-file packet contract](legal_corpus_definition_use_preservation_packet_v2.md#opt-in-parent-bound-normdefinition-packet).
It adds three explicit entry points:

- `prepare_parent_bound_norm_definition_preservation_index_v1`
- `write_parent_bound_norm_definition_preservation_index_v1`
- `lookup_parent_bound_norm_definition_preservation_index_v1`

Preparation takes packet files, typed preparation and bound report, all seven
packet-validator keyword inputs, independently retained
`expected_packet_observation_sha256` and finite `created_at`. Writes use those
inputs with optional `now`. Lookup additionally requires independently expected
complete `expected_key_digest` and `expected_entry_digest`. Writes and lookups
regenerate the projection before and after I/O, including closing replay for a
true miss. A failed post-write operation may leave a row; no successful operation
receipt or rollback is promised.

The projection/operation schemas are
`legal-corpus-parent-bound-norm-definition-preservation-index-projection/v1` and
`legal-corpus-parent-bound-norm-definition-preservation-index-operation/v1`;
the profile is `retained-parent-bound-norm-definition-receipt-consistency-index/v1`.
All fifteen existing proof-key dimensions remain effective, binding complete
report/preparation commitments, mode, norm, all context/alternative references,
explicit premises, theorem/module registry, packet inventory and producer/binary
identities. Observation timestamps are custody-fenced but excluded from the
semantic key.

Entries remain UNKNOWN with CANDIDATE result authority, NONE evidence/trust and
negative cache polarity. Retrievable observations retain `proof_usable=false`,
false accepted execution/outer operation and four integer-zero masks. Existing
official-V2 and direct parent-norm profiles keep their original contracts and
qualification generations.

Use `DuckDBProofStore(connection=caller_owned_connection)` for explicit SQL;
the caller owns the connection, filesystem and exclusive transaction use. The
index opens no connection. Three separate SQL cohorts each passed **one case /
three ordinary phases**: genuine write with full-entry readback, cold public
lookup hit from an owned copy of the closed database, and true `None` miss from
a fresh empty database. Actual SQL covers `body_with_membership` only. Direct
store invalidation after the hit is separate; no second public lookup is
claimed. The miss records the sealed B expected key, policy and masks; it
returns no operation or entry.

The selected index custody controls passed **40 cases / 120 ordinary phases**
(39 new and one existing), with subsequent reader-return faults explicitly
instrumented after genuine baseline replay. The [qualification record](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-norm-definition-preservation-20261025.json)
binds these separate frozen-source scopes. Successful persistence retains
negative engineering observations; `durable_storage_verified`, proof usability,
outer-operation acceptance and training/gold eligibility remain false/zero.

The qualification harness may reuse committed ordinary-data capsules at the
same frozen producer and physical paths to avoid repeating fixture construction.
Every public operation still performs genuine current replay. Capsules are
private test/harness data, not a new public cache API or relocation mechanism.
