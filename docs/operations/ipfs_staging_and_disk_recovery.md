# IPFS staging files and physical disk recovery

The router's file-oriented providers need temporary inputs. Those inputs belong
to one synchronous call and must be removed after the consumer returns, including
error and fallback paths. `_temporary_staging_file()` closes and removes only that
input. Kubo block writes, Accelerate byte uploads, and IPFS Kit byte uploads use
the same lifecycle. Provider results, pin behavior, and retry arguments remain
unchanged.

An Accelerate filesystem fallback can separately retain a copy under
`~/.cache/ipfs_accelerate/files`. That copy may contain unique legal source data;
it is not the router's temporary input. The cleanup helper does not delete it.
The existing simulated-CID fallback is also unchanged: a simulated identifier
does not establish remote storage, retrieval, a proof, or Lean admission.

## Check the three different capacity measures

1. Measure the actual filesystem at the path that will receive the data, including
   non-root available bytes. `df -B1 PATH` and `psutil.disk_usage(PATH)` report the
   capacity ordinary workers can use.
2. Check the campaign ledger's observed usage plus outstanding reservations.
   Raising this cap allocates no filesystem blocks. Releasing an unused promise
   also does not reclaim physical files.
3. Check live native grants and the unchanged supervisor disk watermark. A
   running process or accepted resource reservation is not semantic qualification.

Use the existing resource-control path for maintenance and retain before/after
receipts. Global free-space changes also include other writers, so report the
allocated bytes removed from the selected cache separately from the net change
in filesystem availability.

## Safe cleanup order

- Inspect a few explicit cache and runtime roots first. Bound directory scans,
  run them at low I/O priority, and account for hardlinks once per inode.
- Purge disposable pip and npm download caches through their installed tools,
  after checking for active installers. Keep installed environments separate.
- Run UV pruning without `--force`, offline and with a bounded wait. If UV says
  its cache is in use, retain it. Cached interpreters and libraries may be mapped
  by live language servers.
- Keep model weights, archived checkpoints, source corpora, deferred canaries,
  active databases, native failed-attempt evidence, and foreign worktrees until
  their actual owner and retention conditions are established.
- For suspected staging originals, require exact ownership, file identity,
  content hashes and a verified retained copy. Old age or a `tmp` basename alone
  does not establish that legal source bytes are disposable.

Do not truncate a DuckDB database, delete its WAL or locks, close another worker's
descriptors, or clear active queues to make a disk gate pass. A deleted open file
does not release its blocks until its last handle closes. A memfd uses a different
backing store and is not evidence of reclaimable root-disk capacity.

## Avoid repeated full checkout growth

Shared Git objects reduce object-store duplication, but each full checkout still
materializes tracked documentation, evidence and test fixtures. Prefer an
explicitly scoped staging manifest or sparse checkout when its validation
contract allows that scope. Account for actual checkout and build output before
launching parallel qualifications. Never hardlink mutable source files between
isolated workers. Retain failed qualification materials when their native
acceptance or recovery contract requires them.

## When safe cleanup is insufficient

Add persistent storage and migrate an approved inactive data root, or retire
owner-reviewed redundant material after verified archival. Recheck the actual
destination filesystem and native admission rather than changing the watermark.

On ext4, root-reserved free blocks can make ordinary-user availability much
smaller than total free blocks. An administrator can inspect the actual
superblock with `tune2fs -l DEVICE` and review a nonzero reserve appropriate for
the host. Reserve reallocation is a host-wide capacity change; it does not reduce
used bytes or add a disk. Record the exact old count, preserve an emergency
reserve, and measure the real worker gate and continuing growth afterward.
Restoring a reserve count cannot undo allocations made in the meantime.

## Regression checks

`tests/unit/test_ipfs_backend_router_staging_cleanup.py` exercises provider success,
fallback, failure, retry and cleanup failure. Run it together with
`tests/unit/test_ipfs_backend_router.py`, using the canonical dataset checkout.
These are resource-lifecycle tests; they do not download weights, access a real
IPFS daemon, train an autoencoder, or perform `lake build` admission.
