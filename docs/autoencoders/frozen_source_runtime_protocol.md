# Frozen source runtime protocol

Frozen capsules preserve the canonical import paths while isolating a source
generation from live edits. They are source artifacts, not model checkpoints,
proofs or Lean admissions. Full source, inventory, mount and provenance guards
remain required. Nothing in this protocol enables continuous CUDA or Hub work.

## Explicit existing resource authority

The `prepare_snapshot` and `run_snapshot` convenience APIs and CLI require both
`scheduler_state_path` and `expected_scheduler_policy_sha256`. They observe the
existing scheduler facade and require the existing disk ledger; they do not
initialize or select a default scheduler. The container checks that exact
binding before shared-memory or child-process probes.

For this workspace, the selected existing authority is:

```
--scheduler-state-path /tmp/ipfs-datasets-resource-scheduler-1000.json
--expected-scheduler-policy-sha256 f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661
```

These convenience APIs create a native root owner. A worker already holding a
validation grant should call the low-level `capture_snapshot` under its existing
storage reservation and `source_lease(..., mode="read")`, covering capture,
verification and child drain. Do not nest source leases or borrow another
controller's grant. All writes, including partial failures, must remain in the
declared owned attempt and be retained for normal durable closeout.

## Compatibility and acknowledgment

New captures declare `autoencoder-frozen-source-run/v2` plus exact SHA256/size
pins for the captured snapshot module and CLI. Capture checks these against
the runtime implementations selected by the host module's location. A protocol
label cannot certify an older module or CLI copied into a new capsule.

Before constructing a run reservation, the host verifies the bounded manifest
and its expected digest, then reads only the two fixed runtime producer paths.
The declaration, inventory mappings, captured bytes and currently approved
host runtime must match. Full capsule verification runs again under ownership.
An old or incompatible capsule therefore creates no run claim, starts no Docker
process and writes no run directory through this compatibility-refusal path.

`verify_snapshot` remains compatible with older archive manifests. It verifies
their original bytes for audit; it does not authorize a launch. Preserve older
capsules and their receipts. A runtime module/CLI update requires a fresh
capture or a separately reviewed compatibility mechanism. Do not add a version
field to an older manifest and call it a current producer.

The configuration, container preflight and host acknowledgment bind the same
runtime protocol, configuration digest, scheduler path and policy hash. Missing
or mismatched preflight bindings prevent `host-verified.json` from being
written. The container validates the complete host acknowledgment before
starting the requested command. Resident Python implementation identity and
external dependency bytes still require their existing provenance controls;
the two source hashes do not cryptographically attest execution.

## Validation limits and deployment work

The complete snapshot unit suite covers real private-filesystem capture,
host-edit isolation, tampering, real multiprocessing spawn/queues/locks, explicit
private scheduler metadata, legacy refusal before claims, and the actual host
refusal path with a controlled Docker transport. Controlled transport tests do
not qualify a real container, GPU or shared host policy.

Snapshot fixtures intentionally contain aliases and read-only directories.
Their explicit private pytest profile archives and verifies original metadata
and content, then enables owner-write only through verified fixture directory
descriptors during cleanup. This does not relax production capsule permissions
or the ordinary strict validation profile. The broader merge/legacy suites have
session-escaping subprocesses and need a separately qualified custody scope;
the lease suite also contains FIFO fixtures. No coverage of those suites is
claimed by this snapshot-only run.

The last local metadata probe found a responsive rootless Docker server but no
copy of the pinned image. No image or model weights were downloaded. The
existing launcher is CPU/offline/finite. Its Docker CLI group does not account
for all daemon-created container descendants or aggregate RAM. Those ownership
and cleanup controls remain deployment requirements for real CUDA/Hub work.

Generic pre-directory native admission failures and later preflight failures
can still retain empty daemon claims. This change fixes the incompatible-capsule
path; it is not generic failure recovery. Keep productive convenience-wrapper
launches deferred until custody, resources and cleanup are qualified.

Only actual `lake build <Lib>` grants Lean admission. `lake --version`, a source
capsule, syntax check, training loss or row in DuckDB grants none. The
Constitution remains unformalized.
