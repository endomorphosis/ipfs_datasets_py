# Kernel custody for autoencoder workers

`autoencoder_kernel_custody` observes one explicit cgroup-v2 scope through held
kernel file descriptors. It supplements an actual native resource owner; it
does not create a scheduler, grant resources, launch a worker, or qualify a
model. Its reports use `autoencoder-held-cgroup-v2/v1` and always record
`native_admission: false` and `admitted: false`.

The current module is a custody foundation. The bounded delegated-service
probe is a separate qualification profile. Neither introduces a default
Docker, CUDA, training, or Hugging Face launch path.

## Why a cgroup is needed

The existing native validation owner tracks an isolated direct child's process
group. A descendant can call `setsid()` and leave that group while continuing
to consume RAM or write output. A Docker CLI can also exit while its daemon
still owns running container processes. An empty CLI process group therefore
does not establish that those workers are gone.

Linux cgroup membership is inherited across forks and survives a change of
process session. A held binding can observe the selected kernel subtree and
drain it before output sealing or native resource release. This verifies
benign session changes; it does not confine hostile same-UID code that can
write other delegated `cgroup.procs` files. Production containment requires a
separate profile that verifies the actual container process and restricts its
access to the cgroup filesystem.

The current terminal's root-owned session cgroup must not be adopted or
modified. The probe instead uses a fresh, unique user service with delegated
controllers. Its actual MainPID owns the native reservation. The service
client is not the native owner of the service payload.

## Public API

Import from the pinned workspace tree, after checking the package origin:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_kernel_custody import (
    KernelCustodyError,
    bind_cgroup,
)

scope = bind_cgroup(
    worker_cgroup,
    expected_root=private_service_cgroup,
    expected_owner_uid=worker_uid,
    required_memory_max=512 * 1024 * 1024,
    required_pids_max=32,
    required_cpu_quota_us=100000,
    required_cpu_period_us=100000,
    expected_pid=paused_direct_child_pid,
    allow_drain=True,
)
try:
    observation = scope.observe()
    # The caller must guard its native lease and frozen source/request here.
    # Release the child's pre-work barrier only after all guards succeed.
    drained = scope.drain(timeout_seconds=5)
    assert drained["populated"] is False
finally:
    scope.close()
```

This example describes the binding API, not a complete launcher. The cgroup
and its explicit finite limits must already exist. The actual native owner
must already hold the required CPU, RAM and child-process grant before
productive work begins. The example's 512 MiB and 32 tasks are worker
sub-limits; they do not reserve resources or cover an unbounded owner process.

`bind_cgroup()` requires an absolute unaliased cgroup path that is a strict
descendant of `expected_root`. It verifies an actual cgroup-v2 filesystem,
kernel boot and mount identity, directory and control-file identities, private
UID ownership, domain mode, exact finite CPU/RAM/task limits, disabled swap,
and group OOM termination. If supplied, `expected_pid` must be alive in that
exact scope when bound; its birth and membership are retained. A receipt
cannot reconstruct a binding or authorize a later process.

`observe()` rechecks held descriptors against current paths and controls,
reads bounded counters, and inventories process IDs across the bounded
subtree. Productive observation freezes the child-cgroup topology: new or
removed child groups require a new explicit bind and cannot be silently
adopted. Identity changes, malformed or missing required controls, broadened
limits, changed process membership, and inconsistent observations raise
`KernelCustodyError`. There is no fallback to a CLI process group or a saved
JSON observation.

`drain(timeout_seconds)` requires `allow_drain=True` at the original bind and a
finite deadline of at most 60 seconds. It uses the original held
`cgroup.kill` descriptor and requires hierarchical `cgroup.events populated=0`.
It refuses changed boot, mount, directory or control identity. Limit-value
changes do not redirect cleanup. New descendants in the original subtree are
included in the kernel kill without becoming approved productive workers.
Failure to prove emptiness leaves custody unresolved.

`close()` and the context manager only close descriptors. They never drain,
reap processes, release a native lease, seal outputs or grant admission. A
caller that relies only on `with bind_cgroup(...):` has not implemented
cleanup. The private `_backend` injection seam is for explicit simulations;
its observations are labelled `simulation: true` and cannot qualify real
kernel custody.

## Memory and concurrency accounting

| Observation | Meaning | Required treatment |
| --- | --- | --- |
| `memory_current_bytes` | Hierarchical kernel charge, including anonymous memory, cache and tmpfs | Compare with the whole admitted scope; do not add child charges to an already hierarchical parent charge. |
| `memory_peak_bytes` | Kernel peak charge when `memory.peak` is available | Preserve as optional evidence; a missing optional peak is not a measured zero. |
| `rss_bytes` | The observer does not measure process RSS | Remains `null`; retain any independent native RSS evidence under its own scope. |
| `task_count` / `pids_max_tasks` | Kernel tasks, including threads | Apply the separate kernel task cap. These are not native child-process slots. |
| `process_count` / `process_ids` | Process leaders from the bounded cgroup subtree | Compare children separately with the actual native child-process grant. |
| `populated` | Boolean hierarchical live-task state from `cgroup.events` | Require `False`, corresponding to kernel `populated 0`, before sealing or releasing. |

The service qualification profile reserves and checks the whole service
envelope, including its native owner and worker. Its worker leaf has an
additional smaller envelope. Record both scopes without double counting.
CPU quota and `pids.max` supplement native scheduling; they do not replace its
actual lease or policy checks. Memory counters can change while a process is
active. An inconsistent bounded observation fails closed and must not be
reported as zero usage.

## Required owner lifecycle

1. Verify the exact fresh service name, invocation ID, actual MainPID birth,
   cgroup path, directory identity and finite whole-service limits. Do not
   adopt another existing unit. The probe's bounded controller bootstrap moves
   only its MainPID within that private service, creates its owner/worker
   leaves, and establishes their limits before native acquisition so the
   whole-service observer can guard acquisition itself. This phase starts no
   child, loads no weights, and creates no productive artifacts.
2. Acquire the existing native policy's actual grant in that MainPID before
   productive work. Keep source, request and lease guards throughout the
   productive lifetime; finite service controls do not substitute for a grant.
3. Start a direct native child behind a pre-work barrier, attach it to the
   native owner, move it only into the already bounded private worker leaf,
   and verify its birth and worker-cgroup membership before releasing the
   barrier.
4. During work, monitor the whole service's charged memory and process count,
   as well as the worker leaf's counters. Continue native CPU, RAM, deadline
   and child-process checks.
5. On success, cancellation, source drift, attachment failure or other
   exception, drain the exact worker scope and require `populated=0`. Reap the
   direct child and deliberately adopted descendants, and check recorded PID
   births before declaring them gone.
6. Only then seal outputs, finalize and invoke any superclass exit path that
   can release the native lease or storage claim. If drain, identity or
   emptiness is unknown, retain failure evidence and claims; do not explicitly
   release based on an empty original process group.

The native request still truthfully declares its existing isolated-process-
group scope. The supplementary kernel receipt describes the new cgroup
checks; changing the request's label alone would not add custody. Scope
observations must also guard output sealing because a surviving descendant
could still write while an output inventory is being formed.

## Qualification boundaries and remaining work

The finite no-image probe uses a dedicated user service with finite
`RuntimeMaxSec`, `MemoryMax`, `MemorySwapMax`, `CPUQuota` and `TasksMax`,
`KillMode=control-group`, and a private delegated worker leaf. It tests an
intentional `setsid()` descendant and a small touched anonymous allocation.
Normal and injected-exception paths must record actual kernel observations,
the exact native reservation, and drain/reap/closeout evidence. Execution
results belong in the corresponding evidence report; this guide does not
assert that a probe has passed.

Its root systemd envelope covers the owner plus worker. An outer service
termination ceiling is a separate safety bound, not a native resource grant.
The probe cannot establish Docker daemon/init custody, GPU accounting,
online Hub transfers, training throughput or reconstruction fidelity. The
absence of a locally pinned container image remains a separate gate; do not
download an image or weights to make this probe pass.

The existing supervisor's combined cgroup/PID-namespace quiescence helper
cannot be reused unchanged for a container launched with `--pid=host`: that
namespace includes unrelated host processes. A production profile needs an
exact container cgroup binding and separately appropriate namespace checks.

Fatal owner death and stale native-lease recovery remain a separate
qualification problem. A native recovery rule that observes only the owner's
PID cannot by itself prove that a daemon-owned or kernel-scoped payload has
stopped. Do not promote this module or a successful benign probe into a
production launcher until those release/recovery paths are bound and tested.

Nothing here changes compiler or decoder success criteria. A compiled IR,
decompiled sentence, model loss, bridge target or database row is not a Lean
admit. Only an actual `lake build <Lib>` admits Lean. The Constitution remains
unformalized.

Relevant references: [Linux cgroup-v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[systemd delegation documentation](https://systemd.io/CGROUP_DELEGATION/), and
[frozen source runtime protocol](frozen_source_runtime_protocol.md).

## Qualification status on 2026-10-16

The complete observer unit suite passed 92 tests using explicit simulated
kernel fixtures. The real service bootstrap verified its fixed kernel
controls, but native F07 admission failed before any productive child started.
Its storage claim remains retained as failure evidence. No actual worker
drain, normal completion or injected-exception qualification was obtained.

| Check | Actual coverage |
| --- | --- |
| Complete simulated observer suite | 92 passed; simulation only |
| Fixed service controller/startup verification | Verified before native acquisition |
| Actual service native resource grant | None obtained |
| Real worker/session-escape and memory probe | Not qualified; no child started |
| Normal and injected-exception worker cleanup | Not qualified |

The latest recorded native rejection was `proof_pid_headroom`: F07 required
128 available PID tasks, while the service-visible sample had 63 available
under a 64-task limit. That same sample had 1,477 MiB available memory and
1,536 MiB total; the policy's conservative memory headroom was 24,922 MiB,
with 8,192 MiB of reported root reservations and a further 1,536 MiB request.
The recorded decision names the PID gate; the memory figures expose an
additional mismatch between this small service envelope and host-level
admission accounting. Earlier attempts also observed CPU pressure above the
50% limit, but CPU pressure was not the sole cause: the final recorded sample
had 30.76% CPU stall and still refused admission.

The pinned native sampler conservatively combines host and visible cgroup
capacity while admission accounts for global root promises. Acquiring that
global grant from inside a fixed 1,536 MiB, 64-task service cannot satisfy the
observed headroom requirements. Increasing disk allocation does not address
this RAM/PID admission mismatch. F07, the fixed service limits and all retained
failure claims remain unchanged.

The actual diagnostic is
`artifacts/legal-ir-kernel-custody-20261015/actual-admission-refusal-v1.json`
under the workspace root. It records the historical native refusal, retained
claim, absence of a native grant or productive child, and the stopped service.
It is evidence of refusal, not admission.

A future profile needs an explicitly reviewed separation of host admission
capacity from the worker's confinement envelope, or admission before worker
confinement with an independently qualified owner lifetime. Broadening limits
for admission and shrinking them afterward has not been established under
this fixed-unit contract. No sampler or policy override, two-phase profile,
production Docker qualification or other productive launch is enabled by this
work.
