# Join durable disk accounting to an existing host reservation

`DaemonResourceReservation(..., parent_lease=lease_or_token)` now allocates a
native child from the existing global scheduler. Omitting the argument preserves
the current root-admission path. The same durable named-root disk ledger and
process-group RSS observer remain responsible for storage and sampled usage.
There is no additional whole-host CPU/RAM reservation.

The parent must be an exact native `ResourceLease` or `ResourceLeaseToken`.
The native scheduler validates its capability, host state, live ownership and
remaining capacity. Public records contain only its lease ID. They never contain
the capability key. Closing this owner releases its child, leaving its parent
under the original owner's control.

For this opt-in route, revoked parent admission refuses fresh usage checks and
new external-byte charges. A canonical active-lease observation also recovers
dead or expired ancestors before admitting further work. A child launched during revocation is recorded before
the refusal so that live processes still block release. The caller must stop and
reap those processes. Disk claims remain durable until explicit finalization or
`release(artifacts_durable=True)`; cancellation does not erase them.

Nine actual shared-host controls and 145 existing isolated-scheduler/filesystem
controls passed (154 total, zero skips). See the
[evidence manifest](evidence/nested-daemon-resources-20261002/manifest.json).
The global host could change during tests; allocation assertions isolate the
test owner's roots and check real parent/child links instead of assuming other
jobs remain stationary.

This is cooperative admission and polling. It adds neither a filesystem quota
nor a kernel memory limit. A full supervisor composition must still qualify its
shared storage roots, queue payload bounds, protected validation capacity and
device policy separately.

Consumers can use the live `native_lease` property as their own parent. It
rechecks admission and raises before enter, after release or after revocation.
This keeps the consumer beneath the disk/RSS owner instead of creating a sibling
that competes for the same phase capacity. The follow-up
[ten-control qualification](evidence/public-daemon-native-lease-20261002/manifest.json)
includes a real consumer child acquired through that property.
