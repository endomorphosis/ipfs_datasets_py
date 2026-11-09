# Owned runtime storage observations

`autoencoder_owned_runtime.OwnedRuntimeDirectory` is a filesystem observer. It
does not acquire native resources, precharge storage, launch Docker, authenticate
JSON receipts, archive files, delete files or release claims. The current work
does not qualify Docker, private container namespaces, CUDA, models or Lean.

Compose it with the existing `DaemonResourceReservation`, unchanged ledger and
F07 policy. Keep the evidence attempt regular and inside its existing named
root. Before writing anything, use the existing immutable
`account_external_bytes(key, fixed_runtime_allowance)` API for a separate short
runtime beneath the already named `/tmp/pytest-of-barberb` root. Do not use
`ValidationResourceReservation`, which deliberately forbids external writable
paths and external charges. A resource lane named `HAMMER_LEAN` is not a proof.

The caller creates a new 0700 runtime directory after the charge succeeds.
Bind it while empty:

```python
observer = OwnedRuntimeDirectory(
    runtime_path,
    expected_parent=exact_existing_named_parent,
    expected_owner_uid=os.geteuid(),
    byte_limit=fixed_runtime_allowance,
    entry_limit=20_000,
    depth_limit=128,
)
snapshot = observer.observe()
```

The observer retains parent/root FDs, checks unchanged paths, and takes two
bounded snapshots. It never follows links. Every entry uses `O_PATH|O_NOFOLLOW`
and a Linux descriptor mount ID, including regular-file bind mounts. Owned Unix
sockets, relative symlinks whose captured alias graph stays inside the runtime, and
regular-file hardlinks whose complete link group is internal are supported.
Foreign UIDs, FIFOs/devices, submounts, duplicate directory identities, outside
aliases, excess bytes/entries/depth and observed changes fail closed. Apparent
bytes count each pathname, matching existing ledger inventory conventions.

Alias checks expand captured components in kernel order without touching their
targets. This rejects composed escapes such as `d/back -> ..` followed by
`out -> d/back/../outside`, even though each link's lexical normalization looks
internal. Cycles, more than 40 expansions, missing traversed prefixes and
non-directory prefixes fail closed. A dangling final internal leaf is allowed
as diagnostic metadata, never authority for a later write. The complete graph
has a fixed traversal bound; both snapshots must agree.

Guard the actual native owner and fixed durable charge before and after every
observation. Periodic/final `owner.check_usage(evidence_attempt)` remains the
existing authority for combined evidence plus immutable external charge. The
observer's byte limit and receipts authenticate neither resource ownership nor
fresh directory creation. Source/import custody remains the caller's duty.

The first actual integration should perform filesystem work only: no child,
daemon, container or namespace manipulation. It can exercise a real owned Unix
socket, internal alias/hardlink, byte bounds and retained identity; then close
the socket and preserve regular evidence of observations and cleanup. A short
owned integration root avoids AF_UNIX's 108-byte pathname limit without an
ambient temporary-path fallback. Unit tests use explicitly simulated socket,
FIFO and unsafe-alias metadata over regular fixtures: the existing unit owner
audits live files as well as final artifacts. Actual special integration entries
must be closed and removed by the positively bound caller before strict sealing.

For a later daemon profile, keep native capacity charged through a surviving
guardian until exact container namespace/cgroup and all daemon processes drain.
After the daemon stops, preserve runtime regular bytes plus an explicit alias
manifest/archive; sockets/FIFOs have metadata, never invented stream contents.
Verify archive membership and unchanged originals before removing only the
positively bound ephemeral runtime. The final evidence tree can then satisfy
the existing regular-file seal/finalize path. Keep the fixed external charge
unchanged through finalization, including archive-overlap headroom in the
original storage promise. Unknown ownership, inaccessible rootless backing
data, mounts, incomplete archival or unresolved drain retain the claim.

An archive/cleanup implementation and a dedicated daemon profile remain
separate work. Do not label this alternative live-filesystem profile as passing
the ordinary strict live-attempt policy. Only actual `lake build <Lib>` is a
Lean admit; the Constitution remains unformalized.
