# Retained US Code source reuse and span handoff

October 16, 2026. This reconciles completed source work with the existing
[corpus roadmap](legal_ir_uscode_corpus_improvement_plan_20261015.md) and
[execution design](legal_ir_span_graph_lean_execution_plan_20261016.md).
Their supervisor/LIR dependencies remain authoritative. This document adds no
new task identities, training population or semantic acceptance rule.

## Reuse the completed source work

The September 26 work already inventories the selected 16 corpus shards and
62,931 physical rows, freezes source-group partitions, exports a portable source
package, and independently materializes/reopens an isolated DuckLake delivery.
The earlier October 16 metadata plan missed that completed work; source inventory,
partition creation and source database materialization should not be repeated
merely to begin the span campaign.

The [historical reconciliation](evidence/legal-source-corpus-reuse-20261016/historical-reuse-reconciliation.json)
pins the original receipts, unchanged implementations and retained inputs. Its
availability statements are explicitly stat-only observations at reconciliation
time, separate from any subsequent fresh verification.

| Retained asset | Exact scope |
| --- | --- |
| Source inventory | 16 shards, 62,931 physical rows; SHA256 `38734c403fa9b7bbba8b80f8d4c0ac0529327ae4bc9534b9cf56dd59f4d6caef`. |
| Frozen partitions | 50,282 train, 6,358 validation, 3,147 canary, 3,144 holdout physical rows; 62,839 unique eligible inputs, 59,511 groups and 92 additional same-input aliases. SHA256 `12700969970aac52107eb570167fc09da6e326536335d9e1c00c61b73c9bf45d`. |
| Portable package | 103 files, 263,671,066 bytes, all 33 source fields plus physical ordinal; manifest SHA256 `02e7534050b95e5971e30767e3d1a4a85b266ee6ea4f0fd4c8a0207d8bfcd19c`. |
| Ordered source rows | Digest `9ba5939bc2eab013dfbcb115b66c351e3d03aa3935ccf43346a7b4d0cab33db3`. |
| Recorded embedding coverage | 51 embedded rows, 13 token-limit exclusions, 62,867 unattempted. The upstream manifest's 62,931 declared vector rows are a different artifact population. |
| Historical DuckLake delivery | 783 authored checks; complete ordered native readback and preserved 33 fields. Historical isolated delivery, without production activation or a fresh database open in this phase. |

Source-group partition disjointness does not establish semantic/dependency
isolation or absence of checkpoint exposure. Preserve all existing assignments;
review exposure and semantic connected components before claiming held-out legal
accuracy. Inventory eligibility is not training/gold eligibility.

## Preserve provenance and coordinate spaces

Retained source artifacts keep release commit
`5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`. The selected manifest is exactly
852,161 bytes with SHA256
`0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6`,
matching the October 16 metadata snapshot at
`91ca1838853ac82d7a12dd4ab47d9686f47667f9`. This selected-manifest equality
allows reconciliation; it does not relabel old artifacts or prove whole-release
identity, current payload equality, official-source authenticity or legal meaning.
Unbound current graph/index paths and control-plane discrepancies remain open.

Published `record_json.text` is the source coordinate space for the retained
rows. Exact text, official HTML/USLM and any normalized visible text remain
separate coordinate spaces. Preserve `source_row_id`, ordinal, shard and row
index, record/text hashes, `legal_id`, `entry_cid`, original split, alias count and
embedding disposition. A literal legal ID is evidence, not a rule for selecting
one duplicate or governing interpretation.

## Fresh reuse verification

Native attempt 04 passed all six named checks and four public-owner refusal
controls. The [unchanged report](evidence/legal-source-corpus-reuse-20261016/source-corpus-reuse.json)
records fresh verification of the 103-file closure, regenerated source/provenance
and complete ordered 62,931-row digest. The worker took 66.20 seconds under the
unchanged one-CPU, 2 GiB, one-child, 64 MiB owned-attempt storage reservation
and 300-second productive deadline. Original splits, 92 additional aliases and all embedding
dispositions match the retained commitments.

The [three source companions](evidence/legal-source-corpus-reuse-20261016/selected-source-companions.json)
contain exactly one physical row for each requested ID, with all 33 original
fields plus ordinal, exact published text and zero training/gold masks. The
local capability probe produced exactly one creation and one loopback bind;
its socket closed before the source reads and remained closed at verification.
No disallowed runtime attempts occurred; neither DuckDB engine module loaded.

The [independent native audit](evidence/legal-source-corpus-reuse-20261016/independent-native-audit-04.json)
confirms the exact execution/result/durability receipts, all sealed file hashes
and unchanged source/control witnesses, drained execution, released lease and
storage reservation, and no cleanup error. Its seven sealed files and final
8-file/106,264-byte attempt include the two published exports unchanged. Earlier
failed attempts remain separately documented and their owned reservations are
reconciled without deleting evidence. This is source integrity qualification;
legal meaning, training gold, model improvement and Lean admission remain open.

The [preserved setup/runtime failures and recovery](evidence/legal-source-corpus-reuse-20261016/independent-native-audit-02.json)
and [instrumented import failure](evidence/legal-source-corpus-reuse-20261016/independent-native-audit-03.json)
remain distinct from successful qualification. Instrumented retry 03 identified
one denied `socket.__new__` in the genuine installed `urllib3` import-time IPv6
capability probe before opening corpus artifacts. Its failure is retained; no
counter was cleared or failed operation promoted.

The subsequent import profile permits only the checked probe's one IPv6 stream
socket and same-object bind to `::1` on port zero during the source-binding
import window. The installed probe source is independently pinned and compiled
for exact caller-code comparison; the socket must be closed before source reads
and remain closed at final verification. Allowed capability events are reported
separately from denied operations. Other socket creation/binds, DNS, connections,
sends, extra processes and external writes remain denied. This is a cooperative
Python audit profile, without OS network-isolation attestation or a claim that
zero socket operations occurred. Original native resource ownership and policy
are unchanged; the product and installed SDK bodies are unchanged.

The [closed inputs](evidence/legal-source-corpus-reuse-20261016/reuse-inputs-v01.json)
select the original inventory, partitions, portable package and captured catalog
version report. `SourceCorpusBinding` receives the unchanged captured
`version_after_reopen` and the explicitly selected portable package. Its historical
`package_directory` is descriptive; this operation must not implicitly open the
archived catalog or that historical package copy.

The worker uses genuine public inventory/partition/binding owners and a fresh
complete ordered row pass. Selected source companions request every physical
occurrence for literal IDs `usc:us:10:101`, `usc:us:10:7213` and
`usc:us:10:7214`; missing matches remain explicit. These are exposed engineering
sources with zero training/gold masks and no selected normative target.

## Next bounded deliverable: source-to-span candidates

1. Bind the original source version and verified source companions to a selected,
   independently pinned cache shard and a contiguous range of at most 128 physical
   cache rows. Declare the complete selected source population searched; a
   no-match or ambiguity finding among these three legal-ID companions makes
   no claim about other corpus rows.
   Reuse `legal_span_cache_intake` for the cache records; retain original record
   hashes, span aliases, raw field profiles and every failed/unsupported record.
2. Compare exact published-text fields and enumerate every matching physical
   source occurrence and every overlapping exact substring position. Report no
   match and ambiguity explicitly. Literal IDs, revisions and normalized text
   may be separately reported observations; they must not silently resolve an
   ambiguous byte match, create an alias or select a legal interpretation.
3. Preserve both coordinate namespaces in the candidate result. A cache span
   may not be declared equivalent to an official source until its actual source
   document/view and selector evidence are reconciled. Do not pass these
   published-text selectors to `make_source_binding()`, whose existing contract
   requires original-document/normalized-view evidence.
4. Keep complete provisions, inherited context and original historical occurrence
   obligations explicit. A correspondence candidate supplies source evidence,
   not a reviewed definition, norm, target, graph assertion or Lean theorem.
   Preserve existing unsupported boundaries, including paired formal transport.
5. Freeze an explicit physical selection and cost budget before broadening. Use
   candidate counts, unresolved/missing populations and complete readback to
   decide the next batch. Reuse the portable package and existing catalogs rather
   than introduce another competing source database or identity authority.

Once correspondence and review dependencies close, the existing execution design
continues with a complete definition, norm and second scope-valid use. The
qualified byte target/example contract can transport reviewed targets; it is not
a trained decoder. Compatible old checkpoints and embeddings stay reusable in
independent 8D/384D/768D lanes, separated by IR family, schema/version, decoder
task and producer/token profile. New semantic training, teacher qualification,
scoped graph acceptance and actual `lake build legal` retain their existing gates.
