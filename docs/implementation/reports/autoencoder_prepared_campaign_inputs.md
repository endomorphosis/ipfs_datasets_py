# Reusing campaign preparation within one owner operation

Implementation report, 2026-09-26. The v8 owner now passes its already prepared
campaign context from staged-artifact authorization to input verification within
the same operation. It avoids a second top-level decode of the inventory,
partitions and receipt set. Exact job bindings, frozen role authorization and
fresh artifact checks remain required. This builds on the
[campaign job integration](autoencoder_campaign_training_jobs.md); it does not
change a training job, worker receipt, verification summary or daemon handoff
schema.

Implementation and the bounded capture-r2 offline qualification passed:
**605 regressions, exact six-record input bindings and one unchanged package
snapshot across tests and probe**. In the controlled preparation comparison,
median owner input resolution fell from **15.518037 to 7.864813 seconds** by
reusing the prepared context. This measures preparation only, with two
observations per path. Native checkpoint qualification remains deferred.
The earlier r1 capture remains failed after a concurrent
`logic/autoformal/supervisor_loop.py` edit; its timings remain unqualified.

The relevant implementation is
[`autoencoder_campaign_job_inputs.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_job_inputs.py)
and
[`autoencoder_training_coordinator.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py).
The existing owner flow first checks staged campaign metadata and preflights
both training and validation roles. It then verifies the selected CAS receipts
and sources. Previously, the following worker-input verifier decoded the large
campaign roots again. The owner now passes the private prepared context directly
to the selected-byte verifier and drops its reference immediately afterward,
including between successive jobs in a loop.

The context binds the full canonical job SHA, including exact metadata and
selected artifact descriptors, paths, sample membership and role order. It
belongs to its creating thread and can be consumed only once. A same-thread
consumption attempt consumes it even if the job is mismatched or subsequent
verification fails; a retry requires fresh preparation. It cannot be serialized.
Membership and selected-artifact summaries are held as immutable bytes and
returned as detached dictionaries. Checks also bind the prepared object's
fields and the decoded codecs' immediate frozen fields to their original
identities.

These are constraints on a trusted private Python interface, not a security
capability against arbitrary reflection or code execution in the owner process.
The context is not stored on the registry, published in a result, transferred to
another worker or cached between jobs. There is no persistent cache, process-wide
campaign cache or new trust in a previous verification receipt.

Before reading selected source or producer bytes, the verifier reopens and
hashes all five exact metadata artifacts: inventory, partitions, receipt set,
projection and manifest. Bounded regular-file and no-follow checks still apply.
It then verifies the selected manifest, vectors, source selectors and original
producer provenance, including the existing final selected-closure checks.
The verifier hashes the metadata files again and rechecks the full job and
prepared object identities before returning. Changed or missing metadata cannot
be accepted merely because a decoded object is already resident.

The three top-level campaign loaders run once for a prepared owner operation.
Their existing nested codec constructors and full inventory/grouping
revalidation remain unchanged. This optimization does not claim that every
internal constructor now runs only once or that whole-campaign setup is free.
The normal standalone worker-input verifier still prepares its own exact
context, and an offline daemon consumer still performs its independent input
verification. Existing source-provenance guards remain in force.

No model state or optimizer behavior changes. V8 still supplies ordinary list
input embeddings and retains its existing options for complete shared targets,
Arrow feature weights and sparse candidates. Optional Arrow feature weights
remain independent of input-vector storage. Prepared metadata reuse neither
adds an Arrow input format for multiple receipts nor changes the selected
Python training backend.

The same milestone also fixes a specific resource-accounting race in
[`autoencoder_daemon_resources.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py).
A shared named root can contain another process's temporary directories. In
the preceding r7 artifact audit, `/tmp/pytest-of-barberb/pytest-2409` disappeared
after discovery but before a later census visit. Final global accounting failed
even though the owned artifact probe had finished. The failed audit and its
retained reservation remain historical failures; this code does not clean them
up, release them retrospectively or relabel the run as passed.

Only the nonstrict shared-root census now tolerates confirmed disappearance of
a previously discovered descendant or entry. Queued directories retain their
named root identity. A separate descendant validator checks each below-root
component without following symlinks and returns absence only for a genuine
`FileNotFoundError`. If opening a directory fails after that check, the census
revalidates the path before deciding it disappeared. A dangling symlink cannot
masquerade as an absent subtree. A missing entry is likewise confirmed through
its containing path and a fresh no-follow stat.

Strict owned-attempt scans still fail on missing paths or entries. Named roots
must exist with their original identities before descendant visits and at the
end of the census. Root replacement, symlink paths, non-directory substitutions,
permission errors and unrelated filesystem errors reject. Surviving symlink
and special entries retain their previous lstat-byte accounting in shared
scans and their rejection in strict scans. Disappearing entries still count
against the existing inventory entry bound.

The inventory result shape, named storage scope, quota arithmetic, free-space
checks, ledger locking, lease handling and outstanding reservation charges are
unchanged. Failed claims remain fully charged. The census is still a cooperative
observation of named roots, not an atomic filesystem snapshot or kernel quota.
This change permits ordinary concurrent deletion without hiding type or
permission failures or weakening the stricter owned-attempt accounting.
Persistent substitutions visible at the checked boundaries reject. The
pre-existing interval between pathname `lstat` checks and `scandir` remains;
this implementation does not eliminate arbitrary adversarial symlink swaps
between those operations or provide an atomic descriptor-based tree walk.

The completed controlled probe used the same archived six-record batch—three
training and three validation records—with its exact published-corpus roots,
projection, original producer leaf and selected source files. It creates an
isolated fixture registry. An opaque metadata placeholder anchors the registry's
base version; no model loader opens it as weights. The probe neither constructs
an autoencoder nor generates new embeddings, trains a checkpoint or evaluates a
legal-IR bridge.

The comparison has two paths under the **current validators**:

| Path | Work performed |
|---|---|
| A: deliberate recomputation control | Run the current owner metadata/CAS preflight, discard its prepared context, then run standalone input verification, which prepares again |
| B: actual owner reuse | Run `registered_corpus_job_inputs`, passing the prepared context through the same owner operation |

The order is A, B, B, A. Every result must preserve the exact job SHA and complete
run, variant, job-artifact and corpus-verification bindings. The probe separately
compares these verification results with standalone worker input verification
and the offline daemon consumer. It reports each trial, the two per-path
medians, their difference and ratio. This is a controlled estimate of redundant
metadata preparation under current code, not a replay of the earlier source
tree or a historical checkpoint training baseline. Two observations per path
provide limited precision and do not establish a broad workload speedup.

The probe uses one worker, metric disk-cache flag `0`, bridge names `[]` and
prover evaluation `false`. OS page-cache state is uncontrolled, so neither path
is claimed cold. No cross-job metadata cache is used. Owner resolution, full
daemon export, offline consumer opening and checkpoint-provenance construction
have different scopes and are timed separately. Their costs must not be
reported as wall time per legal span or bridge-on evaluate.

| Current audit field | Status |
|---|---|
| Regression test totals and receipt | Capture-r2: 605 passed, zero failures/errors/skips |
| Full package, test-input and protected-checkpoint guards | Passed; all 7,759 package sources identical across test/probe snapshots |
| A/B/B/A trial wall times | 15.627378 / 7.909379 / 7.820246 / 15.408695 seconds |
| Recompute/reuse median difference and ratio | 7.653224 seconds saved; 1.973097× preparation ratio, approximately 49.3% lower wall time |
| Complete binding and verification equality | Exact equality across all four owner trials, standalone worker verifier and offline daemon consumer |
| Owner export and independent consumer phase times | 15.718447 / 7.874023 seconds, separately scoped |
| Resource release and retained historical claims | R2 reservation and scheduler lease released; no live owned children; failed historical claims retained |
| Post-capture closeout | Passed: all 38 checks true, no diagnostics |
| Native checkpoint comparison | Deferred by user |
| End-to-end training gain or held-out improvement | Not established |

The completed [capture-r2 audit](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-recapture-20260926/capture-r2/audit-receipt.json)
records `passed: true`. Its
[regression receipt](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-recapture-20260926/capture-r2/tests/prepared-campaign-tests-r2-receipt.json)
records 130.825424 seconds of process wall time for the 605 tests. The whole
resource-wrapped audit took 234.676439 seconds. Package source snapshots match
across the test and artifact probe, and test/harness inputs, archived source
artifacts and protected checkpoints remained unchanged. The
[artifact report](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-recapture-20260926/capture-r2/probe/prepared-report.json)
also confirms exact canonical bytes and SHA identities for 48 archived v1–v7
jobs; it does not reopen their historical model inputs or execute them.
The [final closeout](evidence/autoencoder_control_plane_plan/prepared-campaign-inputs-closeout-20260926-r2.json)
passes all 38 checks with no diagnostics. It freshly verifies all 7,759 current
package sources, test/helper identities, staged closure and protected artifacts,
plus the durable ledger/lease release and absence of owned process groups.
The separate failed-r1 claim remains retained.

| Separate artifact preparation phase | Wall seconds |
|---|---:|
| Verify 48 archived job identities | 0.236107 |
| Decode the exact six-record manifest | 0.006819 |
| Stage campaign and selected artifacts | 0.128324 |
| Standalone worker input verification | 8.027404 |
| Owner export, including consumer verification | 15.718447 |
| Open offline consumer after registry closes | 7.874023 |
| Derive checkpoint provenance | 0.000064 |

The enclosing times and individual phases have different scopes and are not
additive. The A/B/B/A comparison uses two observations per path and current
validators; the 1.973097× ratio is not an end-to-end training speedup. The report
retains `speed_claim: false` for broader model performance. Its six-record
sample count, one worker, bridge names `[]`, prover flag false, metric cache `0`
and uncontrolled OS cache remain part of the measurement identity.

The [resource-release receipt](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-recapture-20260926/capture-r2/resource-release.json)
records an explicit durable release with no live owned process. The audit
reserved two CPU slots and 2,048 MiB of cooperative memory; the artifact probe
itself used one worker. Its 1,000,000,000-byte disk reservation included an
800,000,000-byte external fixture charge. Final owned-attempt bytes were
82,339,915, giving 882,339,915 charged bytes without exceeding the reservation.
The observed fixture directory contained 709,949,463 apparent bytes. This
release does not delete fixtures or release any earlier failed claim; resource
limits remain cooperative observations rather than kernel quotas.

The [capture-r1 regression receipt](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-20260926/capture-r1/tests/prepared-campaign-tests-r1-receipt.json)
records 605 passing tests, 131.312837 seconds of process wall time and unchanged
package, test inputs and protected checkpoints during that test process. The
[outer audit](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-20260926/capture-r1/audit-receipt.json)
remains `passed: false`. The
[probe log](../../../workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-20260926/capture-r1/probe.log)
ends at its package/input closure guard before a final probe report or after-source
manifest is written. A read-only comparison identified `supervisor_loop.py` as
the sole changed path among 7,759 package sources relative to both captured
before-manifests; all 116 recorded code/artifact references and the separately
checked archived manifest/projection still matched at that inspection. This
supports source drift as the failure explanation, not qualification of the
unfinished probe.

The successful recapture uses the bounded attempt directory
`workspace/test-logs/federal-corpus-audits/prepared-campaign-inputs-recapture-20260926/capture-r2`.
Its evidence passes its own final source and resource guards. The prior failed
aggregate, unqualified observations and retained reservation remain unchanged.

The tests are designed to cover exact job/context binding, one-use and thread
constraints, serialization and mutation rejection, current metadata checks,
selected-closure integrity and unchanged result summaries. Deterministic
filesystem race cases cover deleted queued subtrees and entries, strict scan
counterparts, named-root changes, symlink/type swaps, permission errors and
unchanged inventory bounds. The guarded receipts establish those offline
contracts at the captured revision; they do not qualify native training.

Use the remaining phase costs and memory footprint to select the next change.
Standalone input setup still took about eight seconds in this workload. A
broader session cache is only one option and would
need evidence that its retained memory and invalidation cost pay for themselves;
it is not a prerequisite or the automatic next step. This change ends reuse at
one owner operation. The
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md) and
[federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retain the
remaining work on language variants, actual parallel training, publication,
semantic coverage and full corpus provenance.

No source authority, native producer attestation, global held-out qualification
or Lean admission follows from this preparation optimization. Native validation
remains deferred. The Constitution remains unformalized and no span may receive
`roundtrip_ok`. Only `lake build <Lib>` supplies the required Lean admission.
No Mathlib import, weight download, context increase or temperature change is
part of this work.
