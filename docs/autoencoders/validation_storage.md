# Owned validation storage

`scripts/ops/legal_ir/run_owned_validation.py` runs a concrete, frozen validation
request with one actual native grant in `ResourceLane.VALIDATION`. Its storage
claim shares the existing named-root ledger. It does not acquire a training
grant, borrow a lease, initialize a scheduler, change the cap, or change any
acceptance criteria. `lake build <Lib>` remains the only Lean admit.

The supported profiles are trusted, cooperative validation in an isolated
process group, with an explicit sampled birth-bound descendant profile when
selected in the frozen request. Sampling is not a filesystem quota, sandbox
or containment of short-lived unobserved escaping descendants. Do not use this
command for training or inference admission.

## Frozen request

Prepare a unique empty `0700` attempt below an existing named storage root.
Store the request outside that attempt. The default request uses schema
`owned-validation-request/v1` and contains exactly these fields; the explicit
V2 extension below adds one closed profile field:

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
| `process_scope` | `isolated_process_group` or explicit `sampled_birth_bound_descendants` |
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
the strict V1 profile. The explicit V2 contract below declares a bounded live
window for selected symlink/FIFO fixtures. Sockets and other special-file
profiles remain separate. Do not relax V1 inventory or report an unqualified
physical-fixture run as aggregate-storage-qualified.

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

## Explicit V2 physical-fixture contract

The V2 behavior stays in the existing `validation_run_resources.py`,
`validation_pytest.py` and `scripts/ops/legal_ir/run_owned_validation.py` owners.
The [closed qualification](../../workspace/test-logs/federal-corpus-audits/legal-ir-physical-validation-profile-20261021-01/qualification-summary.json) records separate cohorts:
92 original contract checks, 15 corrected-source physical controls, seven
affected launcher regressions and six unchanged public symlink/FIFO cases.
These are 120 passed executions over 113 distinct cases, including 107 owner
controls. The 92-case source snapshot precedes the V2-only umask fix; the other
cohorts bind its corrected source. Each successful cohort closed its original
source, compute, observed descendants and storage owners. The first physical
attempt remains unqualified; its 96 MiB retained claim was explicitly recovered
with actual postwrite census and all ten regular files preserved. No progress
marks from failed attempts are counted as passes.

Use `owned-validation-request/v2` with exactly the seventeen V1 fields above
plus one `physical_fixture_profile`. Existing output paths, positive budgets,
deadline, source pins, process scope, scheduler policy, full storage promise
and external-write prohibition remain mandatory. Its additional field has
exactly `schema`, `root` and `cases`, for example:

```json
{
  "schema": "owned-validation-physical-fixtures/v1",
  "root": "/absolute/attempt/tmp/physical-fixtures",
  "cases": [
    {
      "nodeid": "/absolute/repo/tests/test_refusal.py::test_physical_inputs",
      "entries": [
        {"path": "alias", "kind": "symlink", "target": "original.bin", "target_kind": "file"},
        {"path": "pipe", "kind": "fifo", "target": null, "target_kind": null}
      ]
    }
  ]
}
```

This is only the additional field, not a complete executable request. Replace
both absolute prefixes with the independently selected existing repository and
attempt. The root must be exactly `<attempt>/tmp/physical-fixtures`. Declare
one to 32 unique cases, each with exactly `nodeid` and `entries`; a case must
match an exact frozen `selected_checks` value. Each case has one to four
entries, at most 128 overall. Every entry has exactly the four displayed
keys. Only `symlink` and `fifo` kinds are accepted. FIFO target fields must
both be null. A symlink's `target_kind` is `file` or `directory` and its target
is an ordinary relative path inside the same case.

Entry and target paths have at most eight plain components and 256 characters,
with no absolute spelling, empty component, `.`, `..`, backslash or NUL.
Declared slots cannot duplicate or contain one another. A declared target
cannot be or traverse a declared special slot. The expected absolute symlink
literal is at most 4096 UTF-8 bytes. Unsupported types, duplicate/unknown
fields, invalid targets and excess bounds refuse the request before admission.

Freeze the actual pytest `argv` with exactly one `--owned-physical-fixtures`
flag and the pair
`-p ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest`.
Pin the plugin, launcher, all selected test source files and the original
resource/lifecycle owners. For plugin-invoked requests, freeze full absolute
pytest node IDs, including parameter suffixes, in exact collection order.
Collection must equal `selected_checks`; this creates a fresh explicit request
and does not rewrite historical relative test IDs. The owner parser also
accepts exact generic check names for private non-pytest owner controls.

The owner supplies the paired environment values
`IPFS_DATASETS_OWNED_VALIDATION_REQUEST` and
`IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256` from its own frozen request.
The plugin requires both values and the explicit flag, verifies the complete
request file/hash and its closed schema, and rechecks the request at mapped
fixture boundaries. Ambient environment values cannot opt a V1 owner into V2;
the owner removes both before constructing a V1 child environment. Setting a
flag or environment variable alone grants no resource or storage authority.

After original admission and creation of the six existing output directories,
the owner creates a new mode-0700 physical root and mode-0700 case directories.
The case directory is
`<root>/<sha256(exact_frozen_nodeid.encode("utf-8"))>`; no path resolution,
Unicode normalization or truncation changes those input bytes. Their actual
owner, mode and device/inode identities stay bound. The plugin maps only a
declared test's `tmp_path` to its initially empty case, once per case. Other
`tmp_path` uses retain the existing private-directory fixture. The physical
root sits under `tmp/`, outside pytest's recreated `--basetemp`, so pytest
cleanup cannot replace an owner-bound case directory.

Only a V2 productive child launched by the canonical CLI starts with
`umask=077`. Default directory and ordinary-file creation consequently yield
0700 and 0600 under normal modes, including newly created descendants. V1
continues to inherit the caller's umask. This does not change native budgets,
policy, grant count or cap, and libraries remain responsible for subsequent
mode changes and writable paths. The CLI keeps the original startup barrier,
actual PID/birth attachment, source guards and one native validation owner.

During the live window the owner performs a bounded descriptor-based walk of
the whole attempt, without following declared symlinks or opening FIFO bodies.
Only the declared type at the declared case-relative slot is permitted. An
observed symlink must carry the exact absolute literal `<case>/<target>`;
the observer checks the separately declared target through unaliased,
owned ordinary directories/files, never by traversing the observed alias.
Ordinary regular files remain owned and single-link, directories remain owned
and not writable by group/others, and special entries elsewhere fail closed.
The walk has a 20,000-entry bound, depth 32 over the attempt and depth 16
inside a case. Apparent bytes and entry counts cover the same aggregate
attempt and remain subject to the existing storage allowance.

These are sampled sequential observations. A bounded declared-leaf cleanup
disappearance may keep its already observed size/type charged for that sample;
an observed substitution or unbound disappearance followed by reappearance
refuses success. Root/case identity drift, changed target/type, foreign owners,
sockets/devices and exceeded limits also refuse. Source, process/RSS, deadline,
cancellation, custody and full-ledger checks retain their original gates.
The profile is neither an atomic snapshot, quota nor containment of arbitrary
processes or filesystem writes.

The test's original cleanup remains responsible for closing its own FIFO peer
and removing only its positively identified alias/FIFO. The plugin finalizer
verifies an ordinary tree and retains regular evidence; it never deletes or
repairs fixture paths. Every declared mapped case must finish verification
before a successful pytest session is reported. During `seal_results`, after
observed processes stop, the owner permanently closes the live window and returns to the original strict
inventory and durable ordinary-file seal. Leftover aliases, FIFOs, hardlinks
or other nonregular evidence prevent sealing/release. A failed seal cannot
reopen the window. Failure keeps the original evidence and storage promise;
normal compute/storage closeout still belongs to the original resource owner.

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


## Inspect one failed validation without changing its resources

After a successful payload but failed native finalization, keep test results,
storage disposition and compute disposition separate. A completed test report
or durability seal does not establish resource release. The following existing
owner APIs expose bounded observations; they neither recover nor admit work.

`autoencoder_resource_recovery.inspect_validation_reservation(ledger_path,
roots=..., reservation_id=..., expected_request_sha256=...,
attempt_directory=..., ledger_lock_timeout_seconds=5)` requires the exact
validation request, selected reservation and physical attempt under the named
roots. It uses the existing ledger lock without creating a missing lock or
ledger. It returns the selected row's canonical SHA256, current storage status
and nonsecret recorded custody, including the native lease ID and scheduler
policy. It exports no other reservation. An absent row has null status/custody;
recorded storage release does not imply compute release.

Use `existing_resource_scheduler.open_existing_scheduler(state_path,
expected_policy_sha256, inspection_only=True)` for an existing pinned scheduler
facade that refuses state writes and missing lock initialization. Its inherited
`inspect_lease(lease_id, expected_request_id=..., expected_lane=...,
expected_owner_pid=..., expected_owner_birth_marker=...,
bounded_lock_timeout=1)` verifies the exact requested identity and reports only
that lease and its retained descendants. Supply the recorded birth marker when
available; omission is explicitly unverified. Missing state is an error, while
an absent selected lease is a current observation with unknown release history.
Present, expired, cancelled and release-requested states remain distinct, with
separate flags. A release request does not establish stopped descendants.

The inspection method uses a strict existing-file, nonpersisting lock path;
it does not run global stale recovery, renew, acquire or release leases. The
normal constructor remains eager: use the pinned opener's explicit inspection
mode for live existing state and preserve its original policy. The default
opener retains its existing behavior. The inspection-only facade refuses
persistent operations, including admission, release and global recovery. Wrap
opener and inspection in the existing bounded resource-operation deadline when
the facade must be opened for the observation.
The inspection's own deadline bounds lock waits and periodic traversal checks,
not nonpreemptible filesystem IO. No credential or authority token is returned.

Neither observation authorizes recovery. Existing retained-storage recovery
still requires the exact current row hash, dead owner/groups, matching durable
artifact inventory and its other original checks. It handles storage only and
refuses active records. Any later compute recovery or installation decision
must independently bind its own evidence; do not synthesize the missing native
terminal receipt or treat current absence as historical release.

Inspection qualification uses private regular-file fixtures. Unsafe-file tests
inject metadata or no-follow-open errors; they do not create real symlinks,
hardlinks or special files under the strict validation inventory. Those tests
cover refusal branches, not a new kernel containment claim.
