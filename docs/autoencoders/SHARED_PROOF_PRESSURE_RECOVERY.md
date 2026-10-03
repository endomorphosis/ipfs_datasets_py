# Shared proof-pressure recovery

`GlobalResourceScheduler` can pace admission after proof-host pressure clears.
It uses the existing shared state file and lock, native root/child leases,
validation reservation, cancellation, and pressure thresholds. It adds no
second host allocator. The default remains disabled.

Set `IPFS_DATASETS_PROOF_RESOURCE_RECOVERY=1` in every cooperating supervisor,
worker and datasets process before constructing the default scheduler. The
selector accepts exactly `0` or `1`; malformed values refuse. It requires proof
safety, so combining it with `IPFS_DATASETS_PROOF_RESOURCE_SAFETY=0` refuses.
The supervisor's existing `RepositoryResourceBridge` calls the shared default
factory and therefore consumes this policy without another adapter.

An explicitly configured owner may instead use:

```python
config = ResourceSchedulerConfig.for_proof_host(
    proof_recovery_enabled=True,
    proof_recovery_samples=2,
    proof_recovery_interval_seconds=0.25,
    proof_recovery_grants=4,
)
owner = get_global_resource_scheduler(config)
```

Keep the same canonical scheduler path and configuration in every client. A
configuration mismatch refuses while leases, waiters, or recovery remain. Do
not switch an active host to a different state path to bypass that refusal.
Legacy state without the new fields maps to their disabled defaults.
The recovery interval is bounded to 1 millisecond through 1 hour; submillisecond
values refuse instead of collapsing successive deadlines at wall-clock precision.

## Admission behavior

1. A proof-memory, headroom, or stall refusal retains the existing cooldown and
   resets the shared recovery streak. An exception from the proof-resource
   sampler is also a refusal and resets the streak.
2. After cooldown, recovery requires the configured number of healthy readings
   separated by the configured interval. Repeated polling and fairness checks
   at the same timestamp cannot accelerate recovery.
3. The next configured number of ordinary root or child leases are admitted at
   most once per interval. Only recording a granted lease consumes a credit;
   fairness probes, refused requests and cancellations do not. The final paced
   grant also retains its interval before normal admission resumes.
4. Validation, including supervisor cleanup that maps to this lane, bypasses
   only the extra settling and pacing. Existing pressure checks, cooldown,
   parent bounds and reserved-capacity checks still apply. Releasing, cancelling
   and reaping leases do not wait for recovery.

The gate lives in the locked shared scheduler state. A fresh process inherits
the streak and grant deadline. A killed owner's reclaimed lease does not refund
its pacing credit. Relapse or missing proof telemetry restarts recovery.
Ordinary reset refuses during recovery; explicit administrative `reset(force=True)`
retains its existing destructive meaning and must not be used as admission.
The `proof_recovery` snapshot contains phase, healthy-sample count, next sample
and grant times, and remaining paced grants. These are diagnostics, not proof or
task-completion authority.

## Qualification and limits

The focused controls use real native scheduler state, file locking, leases,
independent processes, cold reopening and process termination, with explicitly
injected pressure and time. Separate evidence must label an actual sampler
observation or admission; injected transitions do not qualify an external-load
stress workload. A mismatched canonical host policy is retained as unavailable
instead of rewriting the host's configuration for a probe.

This is a bounded rate of new lease admissions after cooldown, not adaptive
CPU/RAM capacity sizing, per-device GPU admission, a kernel resource limit, or
a bound on all work inside an already admitted lease. No new disk admission is
added, and the supervisor's disk watermark remains unchanged. Validation may
still refuse during genuine pressure. Missing-telemetry claims here cover the
proof-resource sampler: the existing optional PSI probes and optional CPU-only
resource-pressure sampler keep their earlier fallback behavior. Shared timing
uses the scheduler's existing wall clock; external clock adjustment is not a
qualified deployment control.

Run the controls from the datasets checkout:

```sh
python -m pytest -q tests/unit/optimizers/logic_theorem_optimizer/test_proof_resource_recovery.py tests/unit/optimizers/logic_theorem_optimizer/test_proof_resource_safety.py tests/unit/optimizers/logic_theorem_optimizer/test_global_resource_scheduler.py tests/integration/optimizers/test_shared_proof_recovery.py
```
