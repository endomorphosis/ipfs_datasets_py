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
