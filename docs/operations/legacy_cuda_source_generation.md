# Legacy CUDA census source generations

`run_legacy_span_cuda.py` holds the existing cooperative source **read** lease
in its normal external owner. It acquires the lease before importing the native
scheduler/custody implementations and keeps it through engine completion,
descendant termination/wait, and native resource cleanup. The source-lease
module and its lightweight package ancestors necessarily bootstrap before the
lock. The direct owner-to-engine process relationship and ordinary CLI remain
unchanged. The hidden `--_engine` path does not acquire another lease: a waiting
writer holds the admission turnstile, so a nested reader could deadlock while
its own owner holds the source lock.

`--source-lease-timeout-seconds` defaults to 300 and bounds only waiting to enter
the cooperative source generation. It is not a campaign, epoch, batch, CUDA
headroom, or productive-work deadline. Repository identity checks retain their
existing separate five-second Git-command bounds. Waiting emits
`source_lease_wait`; successful acquisition emits `source_lease_acquired` with
the existing `autoencoder-source-lease/v1` receipt. Cancellation observed after
admission exits before native work. A signal received during the lock wait may
remain pending until admission or its bounded timeout.

Writers must use the same canonical repository's **write** lease for the entire
apply, validation, and commit transaction. The existing
`uscode_modal_daemon_runner.codex_main_apply_lock(packet)` call site does this.
Calling `apply_codex_worktree_changes_to_main` directly does not acquire that
lock. `apply_source_merge` advances an integration reference; it is not canonical
checkout promotion. Agents can prepare commits in separate worktrees while a
reader runs, then merge during an explicit source-generation handoff.

For a graceful handoff, verify the exact current bound engine PID and Linux
birth marker against its native owner before signalling **that engine** with
SIGTERM. Its normal STOP path finishes/stages/publishes the current result,
drains executor children, checkpoints/closes DuckDB, and returns. The external
owner continues heartbeats, performs its existing cleanup, and releases the
read lease only when that path returns. Prefetched unfinished rows remain
recoverable at the next generation. Signalling the external owner takes its
existing engine-group cancellation path instead; it is not the same graceful
batch drain. CUDA headroom waits can delay drain. Wait for actual group and
owner quiescence; do not impose a productive-work deadline or force-publish an
unfinished receipt to accelerate a merge.

This is a cooperative protocol, **not an immutable filesystem snapshot**.
Direct editors can bypass the lock; the complete source hashes, canonical
compiler/decompiler/parser tree pin, private engine bytecode, and native custody
checks remain unchanged and reject mixed generations. Descriptors are
close-on-exec and held only by the external owner. SIGKILL or owner death can
release the read lock before an engine or descendant has stopped. A writer
must also verify prior bound work is quiescent before changing canonical files;
lock acquisition alone does not establish crash-safe quiescence. Never unlink
lock files, discard failed claims, reclassify observations as admitted, or
change source trees to get past this boundary.

## Review and verification

The runner hash is included in existing producer provenance. Deployment
requires an explicit reviewed source-authority transition before a fresh owner
launch. A source-generation transition does not itself authorize changing any
native resource policy, claim, service, backend, checkpoint, or success criterion.

Tests select a source-only candidate with `AUTOENCODER_RUNNER_TEST_SOURCE`.
They keep all package and parser imports on the canonical checkout, exercise
real kernel source locks and actual isolated direct child cleanup, and replace
native authority with clearly test-only resource doubles. The fresh subprocess
check uses the actual canonical tree pin and complete producer source guard;
it performs no model loading, CUDA work, downloads, uploads, or Lake admission.
Run them under the normal native validation envelope, followed by existing
runner and source-lease regressions. They do not establish training convergence
or legal formalization.
