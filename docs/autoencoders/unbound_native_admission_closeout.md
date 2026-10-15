# Closing the two unbound native-admission reservations

`scripts/ops/logic/reconcile_unbound_daemon_reservations.py` is an explicit
administrative operator for two reviewed failed starts. It retires their storage
promises while preserving all observed filesystem bytes and reservation history.
It does not admit a workload or prove that any legal text was formalized.

This profile is deliberately limited to reservations
`6eb0cccf427e4ac79e76f15b888313e0` (owner `1020862`) and
`36b6e6ce4be8463fae8cadaa828a4177` (owner `1070490`), each for 1,000,000,000 bytes,
under the unchanged 160,000,000,000-byte campaign cap. It is not an expiry policy
or a replacement for attached-attempt reconciliation.

## Why these claims need a different operator

The normal retained-attempt API requires an attached directory and a nonempty
durable artifact inventory. These two starts failed before attaching an attempt
or launching the inference engine. Supplying an empty inventory to that API
would change its safety contract.

The status `scheduler_admission_failed` alone does not prove there was no grant:
the reservation also catches errors after acquisition. Historical pressure
refusals alone do not prove this either: a request can later be admitted. This
operator therefore requires full terminal journal tracebacks from the exact
owner processes and systemd invocations. Each traceback must traverse the
canonical runner, campaign `open`, reservation `__enter__`, native acquisition,
and terminal `LeaseTimeoutError`. The pinned acquisition control flow makes the
terminal timeout and successful grant branches exclusive. The engine launch is
after the failed `open` call.

The source binding, journal metadata, exact reservation rows, matching refusal
requests, and single-start receipts are separate required evidence. Process
death is only an additional condition. A reused owner PID blocks the operator.

The runner creates or opens its shared runtime directory and owner lock before
acquisition. The operator therefore makes no claim that zero filesystem bytes
were ever written. Its fresh census continues counting those files.

## Evidence and review

The evidence file uses schema
`trusted-unbound-admission-closeout-evidence/v1` and contains:

- `workspace_tree`, `ledger_path`, original `roots` with device and inode, and
  `limit_bytes`.
- `scheduler.state_path` and the exact stored `scheduler.policy_sha256`.
- `protected_active_owner` with the active census reservation ID, PID, and
  `/proc` process birth marker.
- `historical_source_binding` as an absolute path and raw-file SHA256, and
  `source_pins` for the canonical daemon reservation, native scheduler, strict
  existing-state facade, legacy campaign resource wrapper, and legacy runner.
- Two `selected` entries with the allowlisted reservation ID and owner PID,
  canonical JSON digest of the original row, invocation and boot IDs, and hashed
  references to `journal`, `refusal`, and `execution_receipt` files. The refusal
  reference also supplies `keys`, the path to its nested refusal object.

Journal records must preserve trusted `_PID`, `_UID`, `_BOOT_ID`,
`_SYSTEMD_INVOCATION_ID`, `_SYSTEMD_USER_UNIT`, `_CMDLINE`, and
`__REALTIME_TIMESTAMP` fields. Both journal boot IDs must match the current local
boot and actual control lease. Downloaded historical records from a different
machine or boot cannot substitute for local evidence.

Source files must still match the historical source-binding file. Paths must be
owned, bounded, unaliased regular files, and their parents must not be symlinks.
Importing an editable HACC package first is rejected. The operator prepends the
explicit canonical workspace tree in a fresh process; it does not retarget an
already imported package.

Each selected row must have exactly the 17 fields of this unbound failure
profile, with explicit null attempt and child, empty previous children and
external charges, false `artifacts_durable_asserted`, and the reviewed native
request envelope. Attached, partially finalized, externally charged, launched,
or previously reconciled rows are ineligible.

Plan generation performs no inventory scan or ledger write. Its output includes
the complete selected original rows, validated terminal proofs, source digest,
and frozen evidence reference. Review that concrete plan before applying it.

## Native custody and deadlines

Run both modes as descendants of an existing actual native `VALIDATION` root
lease with at least one CPU slot, 1,536 MiB, and four child-process slots. Pass
its public lease ID through `--control-lease-id` or
`IPFS_DATASETS_UNBOUND_CONTROL_LEASE_ID`. Never pass a lease key. The operator
verifies the live lease owner against its actual process ancestry, birth marker,
boot, expiry, lane, cancellation state, and exact policy. It acquires no new
native lease and never initializes or rewrites native scheduler state.

Native checks use the canonical strict facade with
`_locked_state(persist=False)`, without pruning leases or waiters. The native
lock is held only during the check. Because its existing lock acquisition is
blocking, each check runs in a separately bounded custody child with a
three-second timeout. It refuses any matching failed-owner or failed-request
lease or waiter.

Each actual named-root census runs the canonical `_inventory` implementation in
a custody child, preserving its pathname, symlink, special-file, root-identity,
and entry-count semantics. The default child timeout is 25 seconds. There is no
cached inventory or replacement approximation.

Apply uses a 40-second userspace budget after obtaining the disk ledger lock,
reserving at least five seconds before attempting the atomic write. Census or
native-check timeout aborts before mutation. The budget is below the active
census owner's 60-second lock wait. Kernel filesystem operations such as fsync
are not a hard real-time guarantee; no storage policy can make a blocked kernel
operation complete within a fixed wall time.

## Running the operator

The following commands belong inside the existing resource-control wrapper; the
environment variable identifies that wrapper's actual live lease.

```bash
python3 -B scripts/ops/logic/reconcile_unbound_daemon_reservations.py plan \
  --workspace-tree /home/barberb/lift_coding/external/ipfs_datasets \
  --evidence /absolute/path/to/frozen-evidence.json \
  --evidence-sha256 RAW_EVIDENCE_FILE_SHA256 \
  --result /absolute/path/to/new-reviewed-plan.json

python3 -B scripts/ops/logic/reconcile_unbound_daemon_reservations.py apply \
  --workspace-tree /home/barberb/lift_coding/external/ipfs_datasets \
  --plan /absolute/path/to/new-reviewed-plan.json \
  --plan-sha256 CANONICAL_PLAN_DIGEST_PRINTED_BY_PLAN_MODE \
  --result /absolute/path/to/new-closeout-result.json
```

`--evidence-sha256` hashes the exact evidence-file bytes. `--plan-sha256` is the
canonical JSON digest printed by plan mode: sorted keys, compact separators,
UTF-8, and no nonfinite values. It is intentionally distinct from the digest of
the indented plan file. Result paths must not already exist.

## Transaction and result interpretation

Under the disk lock, apply rereads the ledger and validates the complete
selected rows, absent failed owners, protected live census owner, original
roots and cap. It captures all foreign rows, performs one fresh full census,
then rechecks native state, owners, sources, and deadlines. It atomically changes
only the two selected rows: their `status`, new `released_at`, and appended
`explicit_unbound_reconciliation`. Their other original fields remain intact,
including false `artifacts_durable_asserted`. The readback must preserve every
foreign row exactly within that transaction.

The initial result distinguishes the full-claim census from the projection
subtracting exactly two billion reserved bytes. It never labels the projection
as a postwrite scan. The operator releases the lock and yields before a second,
separate bounded lock section obtains an actual fresh postwrite census. Other
owners may legitimately update their rows between those sections. Foreign-row
equality is a guarantee of the write transaction, not a freeze on other work.

- `applied_and_observed`: both claims were closed and the independent actual
  postwrite census completed.
- `applied_requires_postverification`: the write completed, but a later
  readback or observation failed. The result records the failure; do not rerun
  apply or roll the claims back. Inspect the ledger and complete a separate
  read-only verification.
- `write_outcome_requires_verification`: the atomic write was attempted but
  raised before successful completion was known. Inspect the actual ledger;
  do not assume either success or failure and do not retry blindly.

An operating-system kill can interrupt any operator before its final result
file is durable. The appended ledger history includes the reviewed plan digest
so a separate observer can determine the disposition without replaying apply.

The operator does not touch the active census's owner lock, service, queue,
checkpoints, weights, parser, compiler, decompiler, or package sources. It changes
neither the physical-filesystem watermark nor the campaign cap. It deletes no
outputs, resets no accounting history, and admits no training or inference.
Only `lake build <Lib>` can establish Lean admission; nothing in this storage
profile formalizes a Constitution span.

## Test surface

The module exposes `build_plan`, `validate_evidence`, `validate_plan`,
`apply_plan`, `digest`, and the pure `validate_native_snapshot` guard. Tests can
supply an explicitly isolated runtime facade with private ledger, evidence,
process, clock, and inventory observations. Production CLI always constructs
the actual canonical `Runtime`; it has no test-runtime injection flag. Isolated
tests do not qualify the host filesystem or grant workload admission.
