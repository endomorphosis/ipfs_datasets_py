# Native capacity through worker drain

`autoencoder_kernel_fence.KernelDrainFence` combines an actual native child
lease with an original held worker cgroup binding. It uses the existing
scheduler's rule that a released or dead parent stays charged while an
independently live child has not acknowledged release. It changes no scheduler
policy, admission threshold, sampler, or disk ledger status.

The guardian must acquire its own real child before any productive worker
barrier opens. The guardian stays outside the scope it drains. It holds the
source read lease and original cgroup descriptors through cleanup. Passing a
public lease dictionary, receipt, DuckDB row, or cgroup path cannot establish
this custody. The native API supports a private `ResourceLeaseToken` for
cross-process child acquisition; its secret must never be logged or stored in
dataset rows. This class accepts the resulting actual owned `ResourceLease`,
not a token or reconstructed public record.

Same-process root and child capabilities can use this utility for ordinary
cleanup, but they cannot survive that process's death. Reports identify both
owner PIDs and whether they are distinct. Owner-death qualification requires
an actual independently surviving guardian process.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_kernel_fence import (
    KernelDrainFence,
)

# Run in the surviving guardian, with its actual acquired native child.
fence = KernelDrainFence(
    guardian_child,
    held_worker_scope,
    scheduler_state_path=existing_state_path,
    expected_scheduler_policy_sha256=reviewed_policy_sha256,
)
fence.guard_work()
# Independently check source, request, controller/worker budgets and actual
# root ownership before opening the caller's productive startup barrier.

# Normal completion, cancellation, deadline or root-owner death:
closeout = fence.drain_and_release(
    timeout_seconds=5,
    before_release=reap_tracked_births_and_check_sources,
)
```

`guard_work()` checks live native ancestry around a fresh held-scope
observation. It refuses revoked work. It does not replace
`observe_controller_worker()`, enforce the worker's memory limit against a
native budget, or prove that the worker belongs beneath the admission
controller. The caller must retain those existing checks. The immutable
resource envelope is read from the actual native state; mutable display
attributes on a lease object do not override that envelope.

`drain_and_release()` permits cleanup after cancellation. It verifies the
guardian's native child is still charged, verifies the guardian is outside
the kill subtree, drains through the original held descriptor, and runs the
caller's reap/source checks. It checks guardian placement again, repeats
exact drain, and rechecks native custody before acknowledging child release.
Independent native children beneath this fence block release. New worker
topology prevents productive observation but does not redirect cleanup away
from the original hierarchical kill descriptor.

A failed drain, changed identity, callback failure, or unknown native custody
cannot reach the release call. There is deliberately no implicit release in
a context-manager exit or destructor. A living guardian's cancelled child
continues to hold capacity, even when renewal cannot restore productive
authority. A successful drain releases only that child. The root can remain
charged for other independently live children.

The consumer check and native release are separate lock transactions. If
another native child appears between them, native release revokes the fence
and defers reclamation for that live child; the postcheck raises rather than
reporting completed closeout. The fence capability is then released and cannot
be reused, while the root remains charged until the racing child drains. This
is not an atomic conditional leaf-release API.

Disk claims are separate. Killing a `ValidationResourceReservation` owner can
leave its disk record `active`, fully charged and unsealed. This class never
turns it into `retained` or `released`, invents a successful result, or invokes
PID/PGID-only recovery while an escaped worker is still live. Such claims
need their own supported, explicitly reviewed reconciliation.

The owner-death fixture uses a fresh delegated service with explicit
`ExitType=cgroup` and a finite service lifetime. A guardian forks before
native lease heartbeat threads exist, inherits the source lease and original
cgroup descriptors, and receives the parent token through a private pipe.
The service behavior must be observed on the actual host; a configuration
setting alone is no qualification. Results belong in a separate evidence
report, including a stale-recovery call while the worker is still populated,
charged parent and child records, exact drain, terminal native state and the
outstanding disk claim.

This mechanism requires a surviving guardian. Simultaneous guardian death,
host failure, hostile same-UID migration, Docker topology, CUDA execution,
Hub transfers and model fidelity remain distinct qualifications. The current
frozen Docker launcher has a different PID-namespace protocol and is not
enabled by this helper. Only actual `lake build <Lib>` admits Lean; no fence
observation or native resource grant does so. The Constitution remains
unformalized.
