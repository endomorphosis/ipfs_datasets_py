# Resource-aware proof execution

The default proof safety profile uses the existing process-safe, file-backed
resource scheduler. Every participating Hammer client must use the same state
path and configuration. This first implementation covers the datasets Hammer
portfolio and nested resource leases; other prover entry points must explicitly
use this scheduler before they participate in its resource envelope.

## Default activation

New workers on Linux automatically select the safety profile when constructing
`GlobalResourceScheduler()` or calling `get_global_resource_scheduler()` without
an explicit config. Set a shared private state path before starting workers:

```sh
export IPFS_DATASETS_RESOURCE_SCHEDULER_PATH=/tmp/ipfs-proof-resources.json
```

Alternatively, configure the scheduler explicitly in each worker:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    ResourceSchedulerConfig,
    configure_global_resource_scheduler,
)

scheduler = configure_global_resource_scheduler(
    ResourceSchedulerConfig.for_proof_host(
        state_path="/tmp/ipfs-proof-resources.json",
        max_waiting_requests=256,
    )
)
```

Use a private writable state location in deployments. Workers must agree on
capacity and policy. Switching policy while leases or waiters are active raises
a configuration error; drain participating workers before changing it. Do not
delete an active state file. An explicitly supplied legacy config keeps its
existing admission behavior, regardless of the environment switch. Operators
can explicitly select legacy defaults with `IPFS_DATASETS_PROOF_RESOURCE_SAFETY=0`.
The safe SMT/ATP portfolio supplies a 1024 MiB default per-solver memory budget,
capped at the configured lane's usable memory capacity, when no limit is supplied.
Interactive prover and JVM budgets are not assigned this SMT-sized default.

## Admission policy

- Detect CPU affinity and visible cgroup-v2 ancestor CPU quotas.
- Allocate 80% of detected CPU capacity, rounded down, with at least one slot.
- Allocate 80% of host/container memory and preserve the remaining 20% as live
  headroom. Container `memory.high` and `memory.max` both constrain capacity.
- Cap environment capacity settings at detected safe defaults. Explicit Python
  overrides are operator policy and should be reviewed before increasing them.
- Reserve approximately one eighth of CPU slots for the `validation` lane on
  machines with more than one proof slot.
- Require positive memory reservations for root and child leases.
- Check live available RAM against headroom plus outstanding root envelopes.
  Envelopes are conservatively treated as unallocated even when their workers
  already occupy RAM. This can reduce concurrency; it avoids spending the same
  free RAM repeatedly during bursts of admissions.
- Block new root and child launches when Linux PSI avg10 reaches 2% full memory
  stall, 50% some CPU stall, or 10% full I/O stall. Missing optional PSI is zero;
  unavailable required memory telemetry blocks admission.
- Record a shared two-second backoff after pressure is detected. All clients
  of the state file, including child leases, honor it. Waiting callers sleep
  for up to one second between checks during backoff, honor cancellation and
  deadlines, and resume automatically only after cooldown and a fresh healthy
  sample. Persistent external load renews the backoff. The scheduler snapshot
  exposes `proof_backoff` with its reason and wall-clock expiry.
- Bound the admission queue to 256 waiters. A full queue raises
  `ResourceUnavailableError`; callers should retry with bounded backoff rather
  than creating more threads. Ordinary acquisition remains cancellable and
  honors its configured timeout.

Memory reservations include tool overhead, libraries, proof inputs, and working
state. A worker must stay within its reservation. These admission checks do not
kill existing jobs when external load increases.

## Hammer budgets

Override the default memory budget for each solver through `HammerPolicy` or
`solver_budgets`. For example:

```python
from ipfs_datasets_py.logic.hammers.models import HammerPolicy
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy

policy = PortfolioPolicy(
    hammer_policy=HammerPolicy(
        allowed_solvers=["z3", "cvc5"],
        timeout_seconds=10,
        memory_mb=1024,
    ),
    max_parallel_processes=8,
)
```

The safe portfolio reduces its width to fit configured CPU, process, lane, and
memory capacity. Individually oversized budgets fail before solver execution.
The standard bounded process runner already passes these
memory budgets to process limits; on POSIX this includes `RLIMIT_AS`, a virtual
address-space limit per process. Custom process runners must enforce equivalent
limits themselves.

This is not aggregate process-tree memory containment. In particular, JVM and
interactive-prover workers need tool-specific sizing, native thread limits, and
eventually cgroup memory containment; do not assume a 1 GiB SMT budget is suitable
for TLC or Lean. The proof profile does not yet integrate every Lean, Rocq, TLA+,
or tactician entry point, or the accelerate supervisor's separate resource lease
implementation.

## Qualification and next integration steps

Use synthetic pressure tests before any many-core benchmark. Measure checked
proof throughput, peak RAM, PSI, cancellation latency, and queue lengths under
bounded workloads. Increase capacity gradually while maintaining headroom.

The next milestones are to connect the remaining prover adapters to this shared
admission authority, enforce aggregate worker process-tree limits, account for
native backend threads, and replace ready-slice barriers with continuous dispatch.
Adaptive growth should follow measured stable operation. Priority-based
cancellation and active-worker throttling require a subsequent runtime controller;
the current backoff pauses new admission and lets existing work finish.
