# Supervisor phase resources

`ParentedPhaseResourceReservation` connects durable phase storage to the real
native phase already owned by `RepositoryResourceBridge`. It restores the
parent contract lost during an earlier merge without changing the daemon's
HAMMER_LEAN root or the standalone validation command's VALIDATION root.

The native chain is one ORCHESTRATION root, a bridge phase, a storage-owner
child, and optional consumer children. The storage child inherits its phase's
lane: a validation phase stays VALIDATION, and training stays TRAINER. Only
the root contributes another host envelope. Native child limits partition
that envelope; no fake lease or second root is introduced.

## Configuration

`RepositoryPipelineResources.reserve` requires explicit
`scheduler_state_path` and `expected_scheduler_policy_sha256`, together with
an existing storage ledger and its exact named roots. Missing state, policy,
ledger or mismatched scope refuses before host admission. It never initializes
or reconfigures the selected scheduler or raises the storage cap.

The standalone bridge retains its historical default for existing callers.
Its optional state/policy pair selects the strict existing scheduler facade.
Production pipeline callers must supply the pair rather than inheriting that
default. Import the workspace datasets tree first; the HACC editable install
and accelerate's older nested checkout are different producers.

For the finite repository diagnostic, pass `--scheduler-state-path`,
`--expected-scheduler-policy-sha256`, `--resource-ledger`, and repeat
`--resource-root` in ledger order alongside `--pipeline-resources`. Its output
must be inside the configured storage scope. Do not create an unrelated ledger
just to bypass the shared budget.

Each `pipeline.phase` needs an existing, distinct attempt directory strictly
below a named root. Storage, CPU, RAM and process demands must fit the parent's
ordinary or protected compartment. Validation and cleanup retain their shared
protected compartment. Native consumers obtain the actual child through
`phase.native_options()` and must release it only after their work has stopped.
The private handoff contract keeps its existing `daemon:<reservation-id>`
request identity. Public receipts never serialize capability keys.

## Lifetime and cleanup

Admission and productive finalization use fresh native ancestry and global
storage accounting. Local watchdog samples check the original directory,
aggregate apparent bytes, source/owner identity, native cancellation, and the
recorded process group without repeatedly scanning all named roots. The
phase's absolute deadline is fixed at construction; a heartbeat cannot extend
it. A native lease's local `.released` flag does not establish that consumers
have stopped or that their allocation has drained.

Normal completion calls `phase.finalize(artifacts_durable=True)` after native
consumers and the recorded OS group have stopped. The caller must have made
its actual outputs durable first; this generic phase API does not seal output
contents or infer their correctness. Use the standalone owned-validation
command when a frozen check manifest and hashed, fsynced result seal are needed.

On failure, the full disk promise remains charged. After the outer context
has exited, the original owner can call
`pipeline.reap_retained(reservation_id, artifacts_durable=True)` to finish
stopped cleanup even after cancellation or deadline expiry. This admits no
new work or host grant, requires all native consumers and the recorded group
to have stopped, and releases only the original storage child and its owned
contexts. A live parent may also use the established protected cleanup phase.
Do not use PID death, lease age, or a heartbeat as a substitute for this cleanup.

Limits are cooperative sampling, not a filesystem quota, kernel containment,
or accounting of descendants that deliberately escape the original group.
External precharges retain their declared-byte contract; mutable external
growth is not monitored by this profile. Place DBs, WAL/SHM, spills, caches and
old/new exports inside the attempt for aggregate sampling. Shared mutable DBs
and arbitrary external writers require a separately qualified profile.

Resource receipts, successful tests and compiler output are not formalization
or Lean admission. Only `lake build <Lib>` admits Lean. The Constitution remains
unformalized, and training/decoder fidelity gates are unchanged.

## Retained foreign coordinator custody

`RetainedForeignPhaseResourceReservation` is a separate qualified profile for
one predeclared external DuckDB coordinator. It uses the same existing ledger,
named roots, storage limit and actual native phase child. Its closed
`foreign_scope` declaration contains `schema="retained-foreign-duckdb-scope/v1"`,
an exact absolute `database_path`, the existing parent's `parent_identity`
(`path`, `device`, `inode`), and `retained_bytes`. The only foreign files covered
are that database, its `.wal`, and the two derived native lock files
`.<database>.lock` and `.<database>.serialized-coordinator.lock`. It rejects
redirected parents, symlinks, hard links, undeclared database companions and
growth beyond the retained bound. It grants no database write or task authority.

The entire job promise remains charged during execution. Watchdog samples add
actual foreign bytes to the attempt's usage and enforce both bounds. After
children stop and artifacts become durable, explicit `finalize` releases the
actual native compute child but retains a real bounded disk reservation while
foreign files persist. Named-root outputs remain in the fresh global census.
Original external charges are archived and removed from the now foreign-only
live charge inventory. Existing v1 consumers already include this retained
reservation in their outstanding total; neither ledger schema nor root scope
is modified. A finalized foreign record is persistent custody, not a released
disk claim, and must not be discarded by generic stale-attempt cleanup.

A later actual native phase can transfer only exact, stopped, durable custody
whose original native child release was recorded. Both promises are charged
before the atomic transfer; the predecessor retains its original owner/lease
identities and links to the genuine successor. Interrupted or active custody
refuses reuse. Ordinary context failure retains the full original job promise.
Disk `release` refuses while any covered foreign file exists. Empty-scope
retirement requires a fresh admitted native phase and a fresh empty-file check
under the ledger lock. Monitoring is cooperative and runs only while the
current finite owner is active; the persistent bound stays charged afterward.
