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

## Bounded shared-target validation (2026-10-15)

Use `run_owned_validation.py` with the actual existing F07 scheduler policy,
a native storage reservation and private attempt outputs; do not copy the full
checkout or mint a separate resource authority. Preserve failed outputs/history;
close only reviewed dead claims through native reconciliation, never ledger edits.
The 160 GB campaign accounting cap grants no CUDA memory headroom.

A complete package-source change invalidates target reuse, including changes
outside the parser. Keep exact sample/configuration/artifact identities and start
a fresh generation. `_ledger(..., lock_timeout_seconds=30)` provides a bounded
metadata wait within the finite worker/owner deadlines; revalidate the actual
live native lease and owner birth after waiting, rather than reuse stale expiry.
Target preparation requires a positive timeout: 300 seconds satisfies that
contract; zero was invalid. Worker 285 s / owner 300 s bounds still apply.

Fresh preparation used eight archived native 384D inputs (six training, two
tuning), each within the unchanged 512-token encoder limit. All eight returned
all five accepted bridge reports; typed compilation separately compiled five
and abstained on three. Outputs were about 25.3 MB within a 128 MiB claim.
Combined bridge preparation took 49.635 s (6.204 s/span); total preparation took
120.718 s (15.090 s/span), including source guards and I/O.
Names: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
`external_prover_router`; provers=false, metric disk cache=0, adapter workers=1,
legal-IR workers=1, sample memory=false. OS/dependency caches were uncontrolled;
this was not a controlled cold run. No model/weight load or download was needed.
These native checks and targets establish no convergence, decoder fidelity,
formalization, or Lean admission. Only successful `lake build <Lib>` admits;
this preparation ran no Lake build. The Constitution remains unformalized.

The subsequent 384D feature smoke accepted one bounded epoch in 8.530 s.
On two reserved tuning sections, cosine rose from 0.827653 to 0.847531 and raw
reconstruction loss fell from 0.00197249 to 0.00191770. IR losses were unchanged.
Both bridge-on tuning evaluations used two real targets and all five names,
provers=false, cache=0 and one worker; 1.743 s before / 1.535 s after excludes
target preparation because the verified bundle was reused. This is repeated
tuning, not independent holdout evidence or formula-decoder training. The
original checkpoint was preserved; the new candidate remains unqualified.
See `../implementation/reports/evidence/legal_ir_shared_target_training_20261015.json`.

An admission refusal can retain a genuinely empty storage attempt. Explicit
`allow_empty_failed_admission=True` recovery accepts only a dead validation
owner's exact pre-custody admission-failure record and empty bound directory;
it checks the full claim against existing capacity before release. The default
path still requires nonempty artifacts. Never create placeholder validation
outputs to qualify for closeout. This option grants no execution or proof.
