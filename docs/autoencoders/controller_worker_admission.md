# Stable admission controllers and confined workers

The `autoencoder_controller_worker` guard separates the scope used by the
native scheduler from the smaller scope that runs a productive worker. It
reads held cgroup bindings and checks numerical budgets. It does not acquire a
grant, initialize a scheduler, interpret a saved lease as authority, or admit
a model, IR or Lean statement.

The fixed 1,536 MiB / 64-task service tested on 2026-10-16 could not acquire
the existing F07 global grant: its own visible limits were below conservative
host headroom and global promises. That refusal remains valid evidence. See
[kernel custody](kernel_custody.md) for the original profile and its limits.

The new qualification arrangement keeps the native owner in a stable
controller scope throughout admission, renewal, and release. A separate child
cgroup contains the productive worker. Controller limits never change after
admission, and the native sampler and policy remain unchanged.

| Quantity | Finite probe value | Meaning |
| --- | --- | --- |
| Controller `memory.max` | 64 GiB | Stable capacity ceiling; this is not a reservation or permission to allocate 64 GiB. |
| Controller `pids.max` | 512 tasks | Stable kernel ceiling, including threads; native admission can still refuse under concurrent demand. |
| Actual native memory grant | 1,536 MiB | Owned by the service MainPID; compared with aggregate controller charged memory. |
| Actual native CPU / child grant | 1 CPU / 4 child processes | Obtained from the existing scheduler and guarded throughout work. |
| Worker `memory.max` / `pids.max` | 512 MiB / 32 tasks | Hard kernel limits for the worker subtree. |
| Admission / validation / service deadlines | 180 / 120 / 360 seconds | Separate finite phases; validation starts after actual native admission. |

The sampler still takes the minimum of real host availability and every
visible cgroup ancestor. Admission still accounts for all outstanding root
promises and unchanged host headroom. The controller boundary adds a
conservative constraint. This arrangement can still refuse under real host
pressure; it provides no guaranteed admission.

The MainPID must remain outside the constrained worker leaf. It performs all
native acquisition, renewal and release operations. A worker consumes the
already owned grant behind its startup barrier. It must not initialize a new
global scheduler or acquire a native child from inside the smaller cgroup.
Existing parented-resource APIs require an actual in-process lease and do not
remove the sampler's ancestor checks.

## Reusable guard

Import from the pinned workspace tree:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_controller_worker import (
    observe_controller_worker,
)

# Caller has independently verified and renewed its actual native owner.
observation = observe_controller_worker(
    controller_scope,
    worker_scope,
    owner_pid=actual_owner_pid,
    native_memory_bytes=actual_owner.memory_mb * 1024 * 1024,
    native_child_process_slots=actual_owner.child_process_slots,
)
# Caller must verify its actual lease again before releasing a worker barrier.
```

Both scopes must be live `BoundCgroup` objects. The worker must hold the exact
controller as its ancestry anchor: path, directory identity, mount and boot
must agree. A dictionary or DuckDB row cannot reconstruct this binding. The
supplied owner PID and budget numbers are constraints, not native ownership
authentication. The caller must maintain the actual owner, source/request and
lease checks around the observation.

The guard reads the controller, reads the worker, then refreshes the controller
before comparing process inventories and memory charges. These are sequential
observations, not an atomic snapshot. Inconsistent observations fail closed;
there is no cached success or fallback to the original process group.

Controller `memory.current` already includes the owner, descendants, cache,
tmpfs and kernel charges. The guard compares that one aggregate with the
actual native memory budget. It never adds worker memory or owner RSS again.
Worker process IDs must be inside the controller, and the owner must stay
outside the worker. Process leaders consume native child-process slots;
kernel task counters separately include threads.

When available, lifetime `memory.peak` must also remain within the numerical
native memory budget. A missing optional peak stays unknown. No peak counter
is reset. Fresh scopes must have no recorded `max`, `oom`, `oom_kill` or group
OOM event. Low current usage after a failed allocation is not successful
resource qualification.

Every report records `native_admission: false`, `admitted: false`, and
`Lean_admitted: false`. It identifies the controller capacity as unreserved and
does not claim a hard whole-controller cap at the native budget. Explicit
simulation reports remain simulations.

## Lifecycle and cleanup

The administrative bootstrap verifies a fresh unique service, MainPID birth,
invocation, cgroup inode and exact finite limits. It owns bootstrap metadata,
not the service payload. The service MainPID obtains its own actual native
grant before any productive worker starts. Bounded Git/source verification
subprocesses belong to initialization metadata; they are not productive
worker or model activity.

After native admission, attach the direct isolated child behind a closed
barrier, move it into the prebounded worker leaf, and verify its PID birth and
membership before releasing the barrier. Keep the source read lease through
draining, reaping, sealing and release. During work, continue live native
guards and scope observations.

On normal completion or any exception, drain only the exact bound worker
cgroup through its held kill descriptor, require `populated=0`, and reap the
tracked original process births. A child that has not yet left the owner leaf
needs separate positive-birth cleanup. Do not kill the owner leaf, which
contains the native MainPID. Unknown identity or quiescence retains the
failure claim and prevents explicit native release.

Output sealing and every superclass exit that can release a native lease must
be guarded by worker quiescence. The injected-exception probe must not produce
a successful result seal: it retains its failed disk claim and releases its
native lease only after verified drain. Independent closeout checks confirm
actual scheduler/ledger state after the service has stopped.

## Qualification limits

The finite probe uses a real 32 MiB touched allocation in a descendant that
calls `setsid()`. The original native process group must be empty while the
worker cgroup remains populated. Normal and injected-exception runs require
real grant, charge, process, drain, reaping and closeout evidence. Execution
results are recorded separately; this guide does not assert they passed.

This is a qualification arrangement for benign session changes and known
source. It does not fix scheduler scope semantics for every deployment, enforce
a 1,536 MiB hard cap over the whole controller, confine hostile same-UID
migration, or qualify fatal-owner recovery, Docker/CUDA custody, online Hub
transfers or training fidelity. No productive campaign is enabled by writing
an observation. Only actual `lake build <Lib>` admits Lean. The Constitution
remains unformalized.
