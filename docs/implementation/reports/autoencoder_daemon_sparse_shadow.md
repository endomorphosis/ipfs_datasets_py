# Complete-state sparse shadow replay

Status: implemented and qualified offline, 2026-09-25. A bounded endpoint diff
now reconstructs all 38 persisted native state components through the existing
sparse patch codec. The full final checkpoint remains authoritative. This adds
diagnostic evidence; it does not change daemon training, candidate registration,
sparse-checkpoint schemas, or the meaning of successful formalization.

The [qualification receipt](evidence/autoencoder_control_plane_plan/daemon-sparse-shadow-20260925-r1.json)
passes for two fixed archived checkpoint pairs. Its SHA-256 is
`76cb352d2c8ad6f5258c23e044d41a1ac2ba546b7b0d25eb0737bf05c2c0e0e2`.
Only `lake build <Lib>` is a Lean admit. No Lake execution occurred and the
Constitution remains unformalized, with no new `roundtrip_ok` span.

## Implementation and scope

[capture_endpoint_patch](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_state_diff.py)
compares exclusively owned native endpoint states and emits the existing v1
patch format. It scans every persisted field, retaining only changed values
for patch encoding rather than cloning the complete weight graphs. Its raw
typed comparison preserves key types and order, float64 bits including signed
zero, deletions, and ordered applied-ID lists including duplicates. Whole
component replacement handles changes that row assignment cannot reproduce.
An explicitly reported unchanged-component witness represents revision-only
advancement; it is not counted as a changed numeric component.

The profile requires exactly 38 known native fields. Active transactions,
observed revision changes, unsupported objects, decreasing revisions and
oversized states are rejected. Bounds are 64 MiB per typed component, 256 MiB
per typed state, nesting depth 64, and the existing 64 MiB/one-million-changed-
entry patch limits. These traversal bounds are not an RSS guarantee. Caller
ownership is required; revision checks do not synchronize arbitrary writes.

[write_checkpoint_shadow](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_sparse_shadow.py)
accepts exact immutable full-checkpoint descriptors and an existing empty
output directory. It pins the canonical logic tree, loads both endpoints,
captures their net difference, discards the first decoded base, and independently
reloads the base for replay. Verification requires:

- Every raw typed component and the exact revision to match the final endpoint.
- Complete canonical native state bytes and plain/metric identities to match.
- A compact final checkpoint to regenerate byte-for-byte using its original
  metadata, lineage and revision.
- Input artifacts to retain their checksums and emitted patch bytes to equal
  the bytes actually replayed.

It writes a diagnostic patch and receipt, without opening an owner database.
Late receipt fsync failures remove the receipt created by that call when its
inode still belongs to the call. Replacement paths are preserved and cleanup
failures are attached to the primary exception. Consumers must require a
successful return and verified artifact closure; an isolated passing-looking
file is not authority.

This is an **endpoint net difference**, not interception or replay of each
intermediate mutation. It can include final effects outside projection, such
as compaction and applied IDs, without nesting a transaction around the daemon.
It does not authenticate the supplied base version or infer optimizer acceptance.
The earlier owner qualification supplies historical provenance for one case;
this offline diagnostic does not acquire a new owner lease. Existing sparse-v1
JSON-anchor restrictions remain unchanged. Mapped endpoint objects are outside
this native-state profile.

## Guarded evidence

The [combined test receipt](../../../workspace/test-logs/federal-corpus-audits/daemon-sparse-shadow-20260925/combined-r1-receipt.json)
records **250 passing checks**, 10.93 seconds in pytest and 13.143 seconds for
the subprocess wrapper. The tests cover exact diffs, codec/transaction/sparse
and native checkpoint compatibility, publication faults, harness checks, and
all 31 semantic gate/pilot checks. All 7,731 package source files and selected
test/harness files remained unchanged. The same package manifest is present
before and after the subsequent offline qualification.

The [independent audit](evidence/autoencoder_control_plane_plan/daemon-sparse-shadow-20260925-r1-independent-audit.json)
also passes. It checks artifact/receipt closure, current source hashes, the six
exact float64 inserts against raw archived JSON, unchanged-case structure,
revision/metadata scope and released resources. It does not repeat native
state loading, patch replay, training or proof work. Its named-root inventory
records 34,651,801,127 charged bytes including the retained 1 GB reservation,
before writing its own 17,440-byte receipt; the shared scheduler has no leases
or waiters at that observation.

Three integration cases use actual corpus-run orchestration and the native
checkpoint writer: startup compaction with synthetic late guidance/TODO/proof-ID
changes, synthetic shutdown insertion followed by real final compaction, and
an unchanged state. They verify all native fields and durable final checkpoints.
Synthetic late changes are fixtures, not evidence of an accepted native
supervisor or guidance update.

The [offline harness](../../../scripts/ops/legal_ir/qualify_daemon_sparse_shadow.py)
runs both archived pairs sequentially in one new child, with no training,
bridge evaluation, proof execution or owner operations. Parent and child deny
network access with seccomp. Exact input, environment, harness/helper and whole
package source guards pass. The original 25,895,338-byte protected checkpoint
retains SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

| Case | Final artifact | Changed rows | Patch bytes | Complete case wall time |
|---|---|---:|---:|---:|
| Historical owner candidate, zero accepted updates | Full compact, 1,664,643 bytes | 0 | 1,459 | 12.339 s |
| Archived accepted three-gate update | Full legacy JSON, 25,895,897 bytes | 6 | 2,916 | 9.456 s |

The second case changes only six entries in `legal_ir_view_logits`. It remains
the earlier **in-sample** accepted update, without a held-out canary claim or
an owner-observed changed-state transition. Both legacy JSON states load with
revision zero; no persisted accepted-step revision is invented. Native schema
defaults are applied by the ordinary loader. Legacy formatting reproduction
is not a requirement; exact native state reproduction is. The first case also
reproduces the full compact artifact's original bytes exactly.

| Phase | Unchanged owner case | Archived six-scalar case |
|---|---:|---:|
| Load full endpoints | 2.965 s | 3.233 s |
| Capture exact endpoint patch | 1.554 s | 1.558 s |
| Collect released graph, reload and verify independent base | 2.360 s | 2.301 s |
| Apply decoded patch only | 0.000141 s | 0.000270 s |
| Verify complete reconstructed state | 2.230 s | 2.248 s |
| Regenerate/check compact bytes | 3.153 s | Not applicable |
| Write and check patch | 0.012 s | 0.006 s |

Capture's approximately 0.029-second hash timer is a subset of its scan timer;
do not add it again. Case wall time includes additional guards and receipt
writing. Child execution including guards took 23.316 seconds; the entire
qualification took 29.606 seconds. The child peak was 511,048 KiB, approximately
499.07 MiB. Both cases share that process and its cumulative peak; the second
case is not an independent cold-process measurement. Filesystem cache state
was uncontrolled.

The existing shared scheduler reserved one CPU slot and 3,072 MiB in its
canonical-trainer lane, with a 1,000,000,000-byte attempt reservation and a
180-second child timeout. No capacity override was used. At release, attempt
files occupied 3,977,613 bytes; the external receipt allowance was 33,554,432
bytes. The named-root charge was 34,646,572,125 bytes against the existing
50,000,000,000-byte limit, including the earlier failed preflight's retained
1 GB reservation. The new reservation and CPU/memory lease were released after
durable artifacts and a dead child group were confirmed. These are cooperative
reservations with usage polling, not kernel quotas.

## Opportunity cost and next gates

The 2,916-byte changed-state patch is much smaller than its 25.9 MB endpoint,
but its complete production and verification cost is 9.456 seconds here.
Full scanning, loading and independent reconstruction dominate patch application.
Do not report the sub-millisecond replay as the cost of accepting or persisting
a model. This diagnostic retains both full endpoints and does not yet save
daemon checkpoint work, DuckDB traffic, or end-to-end training time.

There is **no new wall-time-per-span or bridge-on evaluation measurement** in
this slice: no samples or bridge names were evaluated. Prior bridge receipts
retain their original flags and sample counts. Empty or absent bridge work
cannot establish a faster legal-IR run.

The subsequent [owner-bound shadow slice](autoencoder_daemon_owned_shadow.md)
now binds optional production to owner-controlled completion while retaining
the complete checkpoint. Its qualification uses real description and verification
around a synthetic changed-state execution, with zero accepted optimizer epochs
and no matching evaluation claim. Require native changed-state evidence,
rejection/rollback and recovery coverage,
and exact parent/revision authority before making sparse candidates an opt-in
storage representation. Keep endpoint comparison as an independent oracle for
any future live mutation collector.

Arrow adoption still needs explicit asynchronous snapshot and writer lifetimes,
copy/close failure tests, exact list/mapped behavior and measured end-to-end
benefit. The previous worker feature-table evidence does not establish those
daemon properties. Full federal source inventory, reviewed semantic coverage,
general held-out evaluation, production DuckLake materialization and Hugging
Face publication remain separate gates in the
[end-to-end plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
