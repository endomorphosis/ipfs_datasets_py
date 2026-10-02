# Native CodebaseIR metadata history and scoped artifact retention

This explicit local profile takes an immutable `IntentCodebaseCatalog` discovery
record through the existing `AutoencoderRegistry` operation/event/outbox owner,
the existing `autoencoder_ducklake` delivery journal, and the actual pinned native
`IsolatedNativeDuckLakeHistory` sink. It does not introduce a source, model, proof
or promotion head, a second delivery journal, or another database schema.

`codebase_ducklake_history.py` provides:

- `prepare_codebase_history_request(discovery, record_cid)`: reconstruct the
  native source/semantic discovery record before forming closed metadata.
- `register_codebase_history_request(registry, discovery, operation_id, request)`:
  atomically append an immutable metadata event and outbox row using the existing
  registry primitives. Exactly repeated historical requests resolve before
  requiring captured artifacts to remain available.
- `resolve_codebase_history_request(...)`: resolve the exact operation ID,
  command and canonical payload; a receipt does not imply current availability.
- `deliver_codebase_history(...)`: use the unchanged native delivery worker,
  journal, frozen batch membership, lease generation fences and ACK protocol.
- `inspect_codebase_history(..., registrations=[...])`: report pending native
  acknowledgements for at most ten explicit registrations, reconstruct ACK batch
  content, and query the actual event at its native DuckLake snapshot using
  `AT (VERSION => ...)`. Pending acknowledgement does not assert that a lake
  commit is absent after response loss.

The event records exact source-head, source-owner, policy and semantic-manifest
identities. Optional model/corpus identities are declared association context,
not training lineage or evidence that inference ran. Source observation,
proof/training authority and production activation remain false.

## Durable pins, leases and a dedicated managed artifact namespace

`codebase_history_retention.ManagedCodebaseHistory` is an opt-in wrapper over
those same native owners. It requires a new dedicated CAS root. Its artifacts
are meaningful `codebase-history-candidate@1` envelopes containing the exact
owner-reconstructed history request and a stage-operation identity. The
source/semantic/proof CAS stays separate and is never collected.

One managed profile is bound to each native delivery registry. A second managed
root on the same registry, adoption of an existing namespace without its durable
profile, or changed directory identities refuses. The existing native registry
operation/event transaction owns the control state.
Every command cold-replays the bounded event chain and verifies its exact native
operation receipt. Event and operation populations must agree, so removing a
newest event while leaving its committed operation cannot roll back a pin or
lease. No warm dictionary, in-memory snapshot facade or second SQL head is an
authority. Control events can flow through the ordinary native outbox too.

The public lifecycle is:

```python
managed = ManagedCodebaseHistory(registry, native_history, managed_root, create=True)
candidate = managed.stage(discovery, record_cid, operation="stage-1")
with managed.read(candidate["candidate_cid"], operation="read-1") as envelope:
    consume(envelope)
managed.deliver_and_pin(
    discovery, candidate["candidate_cid"], operation="retain-1",
    source_id="repository-history", output_directory=journal_root,
)
managed.inspect_pins()  # rechecks actual native snapshot and candidate bytes
```

Producer/reader leases are durable and have no timeout that silently authorizes
delete. The native registry owner lock is held across wrapper I/O and the entire
reader context. A concurrent same-process registry close cannot mark a wrapper
dead while it continues to write. A new exclusive owner can explicitly call
`recover_abandoned_leases` to reconcile previous owner generations. Current
leases remain live; unreconciled old leases block quiescence.

`deliver_and_pin` registers the envelope's history request, delivers bounded
frozen batches with the existing worker, independently verifies the actual
native ACK and retained snapshot, then persists a pin binding candidate,
registration, event and snapshot. `inspect_pins` verifies those relationships
again. This profile never expires native DuckLake snapshots or deletes its data
files. A history pin alone does not grant native maintenance permissions.

## Admitted artifact deletion and recovery

An explicit quiescence gate requires no outstanding producer or reader leases
and prevents new admissions and pin changes. `collect` accepts at most eight
explicit registered candidate CIDs. It refuses pinned, unregistered, already
collected, malformed, oversized or aliased targets. Root/namespace filesystem
identities and the original candidate's exact bytes/CID are checked. Candidates
must be bounded regular files with a single link.

Before unlinking any candidate, the owner durably records the exact collection
operation, gate, target CID, device, inode and size in the existing registry
transaction. The physical unlink uses a directory descriptor, repeats the
identity check, and fsyncs the directory. A second native command marks
completion; the gate remains until an explicit release. This sequence does not
claim atomicity across DuckDB and the filesystem.

If the process exits after unlink and before completion, a new native owner
continues the original prepared plan. An absent file counts as resolved only
for that durable exact intent. Missing files before preparation refuse; changed
inodes after preparation refuse. A lost completion response resolves the native
operation and never repeats a completed physical delete. A pending collection
prevents gate release or a different target set.

Only registered managed envelopes are eligible. Unowned CAS files, source CAS
objects, pinned envelopes and native DuckLake metadata/data remain untouched.
This is **not** a generic shared-CAS graph collector, a source-artifact sweep,
a global producer fence, a snapshot expiration implementation, or distributed
atomicity. Direct access to the dedicated CAS outside this wrapper is outside
the selected ownership profile; path defenses detect accidental aliases and
replacement but do not claim safety against hostile same-user filesystem
writers racing syscalls.

## Bounds and failure behavior

The profile permits 512 control events, 64 candidates, 32 simultaneous leases,
eight pins and eight collection targets. Candidate bodies are at most 24KiB,
control commands 32KiB and control events 48KiB. Cold replay preflights a maximum
of 4,096 native operation receipts, each at most 128KiB, before selecting control
receipts. It batches SQL reads to stay inside the native owner's 32-statement
transaction budget. The capacities are explicit qualification limits; there is
no event-log compaction or unbounded daemon claim. New operations refuse when
capacity is exhausted. Admission reserves durable slots for outstanding lease
release, prepared collection completion and gate release before any physical
delete; an ordinary admission cannot consume those slots. Reader lease IDs cannot be reused after release; a
subsequent read needs a new operation ID. Completed stage retries report
historical identity and do not assert current artifact availability.

The actual native tests include process exit after DuckLake commit and after
physical artifact unlink, independent fresh-process recovery, stale owner
leases, exact-operation response loss, duplicate delivery, later snapshots
with earlier retained readback, acknowledgement lag, real concurrent reader
admission, pin protection, deletion, aliases, replacement, malformed/oversized
metadata, event omission and operation drift. The qualification evidence records
initial failures and the correction rather than presenting the first run as
successful.
