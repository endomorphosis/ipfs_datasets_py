# Owned validation storage

`scripts/ops/legal_ir/run_owned_validation.py` runs a concrete, frozen validation
request with one actual native grant in `ResourceLane.VALIDATION`. Its storage
claim shares the existing named-root ledger. It does not acquire a training
grant, borrow a lease, initialize a scheduler, change the cap, or change any
acceptance criteria. `lake build <Lib>` remains the only Lean admit.

The supported profile is trusted, cooperative validation in one isolated
process group. Sampling is not a filesystem quota, a sandbox, or containment of
descendants that call `setsid`. Use a separately qualified exclusive scope when
that stronger containment is required. Do not use this command for training or
inference admission.

## Frozen request

Prepare a unique empty `0700` attempt below an existing named storage root.
Store the request outside that attempt. The request must use schema
`owned-validation-request/v1` and contain exactly these fields:

| Field | Meaning |
| --- | --- |
| `argv` | Actual executable and arguments, without shell interpretation |
| `cwd` | Absolute existing working directory |
| `selected_checks` | Nonempty, unique names of the checks this command executes |
| `source_sha256` | Absolute source paths and their reviewed SHA256 digests |
| `roots` | Exact existing ledger root paths, in their declared order |
| `attempt_directory` | The private empty attempt |
| `outputs` | Exact mapping of `pytest`, `tmp`, `cache`, `db`, `exports`, `logs` to those children of the attempt |
| `declared_external_writable_paths` | Empty list; external mutable outputs are unsupported |
| `process_scope` | `isolated_process_group` |
| `storage_bytes` | Explicit total byte allowance, including temporary overlap and receipts |
| `memory_mb`, `cpu_slots`, `child_process_slots` | Explicit positive native budgets |
| `timeout_seconds` | Explicit positive validation deadline, at most 3600 seconds |
| `scheduler_state_path` | Actual existing native scheduler state |
| `expected_scheduler_policy_sha256` | Exact reviewed policy digest |

Pin the launcher itself, the validation resource module, the native resource
and scheduler sources, and every selected source/check. A fresh process binds
the repository containing the launcher before importing `ipfs_datasets_py`.
The canonical workspace must continue to use `external/ipfs_datasets`; an
editable HACC import is a different runtime and is not a substitute.

For pytest, the frozen `argv` must explicitly place `--basetemp`, JUnit output,
and `-o cache_dir=...` under the respective output paths. Add `-B` to Python
commands. The launcher sets temporary-file and XDG cache variables and disables
bytecode writes, but each library remains responsible for its writable paths.
In particular, configure database files, WAL/journal/SHM sidecars and spill
directories under `db/` or `tmp/`. No path placement is claimed as a sandbox.
Use `--basetemp=<attempt>/pytest/basetemp`, not the pinned `pytest/` directory
itself: pytest legitimately recreates its basetemp. The six stable layout roots
must retain their identities throughout validation.
For regular-file suites, explicitly select
`-p ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest`.
This provides function-scoped `tmp_path` directories through `mkdtemp` instead
of pytest's numbered directories and `...current` navigation symlinks. Fixtures
remain unique, private, and retained; test assertions and selection are unchanged.
The standard `tmp_path_factory` is unchanged. Tests that require its numbered
aliases, or deliberately construct symlinks/FIFOs/sockets, remain unsupported by
this strict storage profile and must use their established validation profile.
Do not relax the inventory or report those runs as aggregate-storage-qualified.

Run from a fresh process with the existing policy and ledger:

```text
python3 -B scripts/ops/legal_ir/run_owned_validation.py \
  --request /absolute/reviewed-request.json \
  --expected-request-sha256 <exact-request-file-sha256> \
  --resource-ledger /absolute/existing-disk-reservations.json
```

There is no outer resource lease. `ValidationResourceReservation` owns both
the one real validation grant and the durable storage claim. The command's
isolated direct child waits at a startup barrier until actual PID/birth
attachment and a fresh full ledger check complete. The launcher rechecks
request/source/cancellation/deadline custody before releasing the barrier.

## Accounting and results

The existing conservative global equation is unchanged:

```text
observed bytes in named roots + all outstanding full storage promises <= cap
```

The local run additionally requires all apparent bytes beneath its attempt to
fit `storage_bytes`. All six output directories count together, including many
small fixtures, mutable DB files, WAL, spills, logs and simultaneous old/new
exports. Hardlinks and reflinks do not reduce the pathname-based accounting.
Private mutable databases are never shared between validators.

A local watchdog samples request/source identity, owner and original group
RSS/process counts, directory identity and aggregate bytes without taking the
global ledger lock. Native lease renewal and explicit fresh full scans are
separate. These are sampled limits; a writer can temporarily grow between
samples, and unrelated producers can consume global headroom after admission.

On successful command completion the launcher reaps the supported group,
writes `logs/execution.json` and the six-field `owned-validation-result/v1`
record, hashes and fsyncs the attempt into `logs/validation-durability.json`,
then calls the native fresh-census finalizer. Claim and grant release occurs
only through that owner. The private inventory records names/hashes rather than
exporting artifact bytes or private database keys. It is not a public Hub export.

On failure, cancellation, source drift, overage or unknown ownership, the
launcher stops/reaps its supported group and retains the claim and evidence.
Do not release a claim based on age or a dead PID. Exact administrative recovery
requires the original record hash, dead owner/groups, matching owned artifact
inventory and durable evidence through the existing recovery API. This first
profile rejects external writable charges so that recovery scope remains real.

Validation result records describe actual command execution. They do not prove
semantic correctness, model convergence or Lean admission. Existing compiler,
projection, logic-family and Lake gates remain separate and unchanged.

### Admission refusals

A storage-capacity refusal from `owner.open` emits one JSON diagnostic to stderr
with schema `owned-validation-capacity-refusal/v1`, then raises the original
`DaemonResourceError("storage reservation capacity exceeded")`. It includes the
existing census's observed bytes, outstanding full promises, additional request,
charged bytes, cap and minimum filesystem free bytes. Separate Boolean conditions
and byte deficits distinguish the cap from the physical-free-space check.

The diagnostic is limited to 4,096 UTF8 bytes and contains no inventory paths,
reservation rows or process identities. It performs no additional census or
pre-admission output-file writes. An unavailable stderr preserves the original
exception. The error's optional `capacity_observation` property returns a detached
aggregate snapshot; unrelated resource errors return `None`.

These numbers describe the failed accounting observation, not a subsequent
reservation or permission to reuse another owner's promise. A refusal at this
initial `_account` occurs before insertion of this run's storage record and
before native grant acquisition. Later failures retain the established claim
and recovery rules above. Preserve the observation, have the relevant artifact
and claim owners reclaim space or complete durable finalization, then create a
fresh request and attempt through the same native owner.

The [source-review handoff diagnosis](legal_source_review_handoff_storage_20261015.md)
records one actual physical-space refusal and its still-pending source workload.

## Scope of integration

This command is the direct validation path. The generic accelerate pipeline
uses a separate explicit parent authority contract, described in
[parented phase storage](parented_phase_storage.md). Its real same-lane child
lives beneath the bridge's existing phase; it does not borrow this command's
fixed root or acquire another independent host envelope. Generic phases retain
their explicit artifact-durability assertion and do not inherit this command's
frozen request/result seal. Other validation entry points retain their existing
behavior until explicitly migrated. No blanket storage qualification is claimed
for all supervisor jobs.
