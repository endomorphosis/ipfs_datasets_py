# Campaign preparation with operation-local root reuse

The guarded capture passed on 2026-09-26: all 682 tests passed, and repeated
preparation of the same primed three-batch page fell from a 66.324950-second
median to 15.117741 seconds (4.387226×, two observations per mode). The reviewed
r3 change reuses decoded campaign roots within one bounded preparation call
while preserving exact artifacts and verification results. All 47 independent
closeout checks passed. This is a preparation speedup; native training validation
remains deferred.

The [qualified preparation profile](autoencoder_campaign_batches_profile.md)
measured 67.286434 seconds for three archived-source batches. Loading the source
inventory, source partitions and embedding receipt set consumed 60.435699
seconds, or 89.82% of that instrumented wall time. Each root loaded eight times:
once for the template, once for direct selection, three times for generated
jobs and three times while sealing the plan. Nested codec validation constructed
24 inventories, 16 partition objects and eight receipt sets. These observations
justify removing repeated decoding before changing a weight or storage backend.
They establish no optimizer, compiler or legal-semantic improvement.

The profile covered 40 training records and seven shared validation records,
arranged as training batches of 16, 16 and eight. It used 47 unique stored
records and 61 record occurrences, with the four embedded holdout records
excluded. Source coverage still includes 13 token-limit failures and 62,775
unattempted unique inputs. The checkpoint was an explicit three-byte synthetic
fixture, not model weights. See the linked profile for its completed provenance,
resource and independent closeout evidence.

## Implemented boundary

The private `_CampaignRootScope` in
[`autoencoder_campaign_job_inputs.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_job_inputs.py)
exists for one lexical owner operation on its creating thread. Its first use
calls the existing three public root loaders, including their nested constructor
validation. It retains the final receipt set's own partition/inventory graph;
the redundant initial upstream objects are not kept in the scope. This removes
repeated root loads across jobs, not nested validation inside the first load.

Reuse binds the exact three declared root paths, SHA-256 digests, byte sizes and
metadata byte limits, the owner object and its CAS root, the creating thread,
the operation token, and the decoded objects and limit fields. Each root keeps
the existing 64 MiB metadata bound. Root access reopens and hashes current files
through the existing bounded regular-file, no-follow verifier. A matching cached
descriptor alone cannot authorize reuse.

The scope also captures a bounded producer-code identity covering 11 optimizer
modules: the campaign-input helper, inventory, partitions, receipt set,
projection, corpus manifest, corpus index, embedding production, US Code import,
training worker and evaluation splits. It checks module locations, function and
method identities, wrapped code, and current source bytes. Source hashing rejects
aliased paths, non-regular files, files over 4 MiB and observed file/path changes
across descriptor and pathname checks. Frozen decoded fields and nested limits
are checked without decoding the campaign again.

This is an internal drift guard, not a sandbox against arbitrary Python code
and not a runtime whole-package attestation. The existing six-source job pins
remain unchanged. Whole-package and dependency stability for a measurement must
come from its separate audit receipts. The completed capture's wider checks are
reported below. Boundary checks do not make concurrent filesystem changes
atomic.

Scope exit or a scoped operation failure invalidates the context and discards
its decoded graph. It cannot be reentered or serialized. A prepared job is still
single-use and bound to the canonical complete specification, including paths
and ordered samples. A same-thread consumption attempt consumes that job's
context even when its job or scope binding is wrong. Failure invalidates the
original captured scope; a substituted unrelated scope does not become its
verification authority.

## Checks retained for every job

Each generated job gets a new manifest, projection and prepared context. Both
training and validation roles must be authorized from the frozen source split
before selected source or receipt I/O. Exact selected descriptor closure, ordered
records, samples, dataset/split identities and the qualified English `us_code`
frontend remain mandatory. Fresh bounded metadata hashes surround selected-byte
verification. Projection verification and source validation still inspect the
selected current bytes and produce the same wire summary.

The coordinator continues checking staged CAS bindings. The generator retains
original selected-path and staged-copy checks, template bindings, output-path
checks and all four final-input barriers. Scope checks also surround staging
and registration. Drift observed at either barrier before registration rejects
the page before its first new `CreateRun`; a failure observed after registration
does not roll back or relabel already queued immutable jobs.

Private helpers carry the scope through template verification, direct generator
selection, each job preflight and final plan sealing. The public worker, owner,
preflight, plan-build and plan-seal entrypoints keep independent fresh
verification. Every batch-preparation call, including a repeat after reopening
the registry, creates a fresh scope. Public signatures, schemas, artifact
formats, job identity rules and registration behavior are unchanged. There is no
persistent root cache, receipt-leaf cache, source-byte cache or cross-job prepared
verification token.

The implementation touches only the campaign-input, coordinator, campaign-plan
and batch-generation helpers. It changes no parser, canonical compiler,
decompiler, target payload, optimizer update or checkpoint format. Shared-target
runtime membership remains deferred where the generator already reports it;
optional Arrow feature weights retain their existing contract.

## Qualification and comparison

The [regression receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-root-reuse-20260926/capture-r1/tests/tests-receipt.json)
records all 682 tests passing with zero failures, errors or skips in 223.025829
seconds for the pytest invocation. The 49 new cases cover exact artifact/summary parity,
eight-to-one root-loader counts, fresh public verification and restart, wrong
job/root/path/owner/thread, expiry, decoded-object and limit mutation, source-code
drift, scope substitution, protected roles, selected-byte changes, callback
failure and registration barriers. These are synthetic offline checks with
injected updates where existing suites exercise training transactions. The
eight-to-one root-loader counts are regression assertions, not instrumented
counters from the archived-data timing comparison. The prior instrumented
profile separately observed eight loads of each root.

The private `_prepare_campaign_batches(..., reuse_root_metadata=False)` control
uses ordinary fresh verification in the current implementation. Setting it to
`True` uses the scoped path; the unchanged public API selects that path. This
permits an explicit comparison using the same current validator code, helper
source hash, registered template, registry, output root and artifact identities.
It does not switch parser trees or revive an older implementation.

The [archived-data probe](../../../workspace/test-logs/federal-corpus-audits/campaign-root-reuse-20260926/capture-r1/probe/reuse-report.json)
used the public API to register one page without timing, then measured repeated
preparation in A/B/B/A order, where A recomputes roots and B reuses them within
that call. All four complete calls used the same isolated owner, already queued
page, current helper and validators, without loader instrumentation. All returned
exact generation reports, job and plan artifacts, preserving the archived
vectors/roles/configuration and all 62,839 input dispositions. Queued runs,
template and checkpoint head stayed unchanged. The new regression suite
separately verifies owner restart and fresh public verification; the timed
archived-data probe stayed in one owner. These timings do not establish the
speed of first-time registration.

| Observation | Root treatment | Complete repeated-preparation wall seconds |
|---|---|---:|
| A1 | Recompute | 66.918775 |
| B1 | Reuse within this call | 14.954624 |
| B2 | Reuse within this call | 15.280857 |
| A2 | Recompute | 65.731126 |

The recomputation median was 66.324950 seconds and the reuse median was
15.117741 seconds: 51.207210 seconds saved, or 77.2066%, with a 4.387226× median
ratio. These are two observations per mode on one primed page, not a broad
throughput distribution or a cold-start result.

Exact artifact-byte parity applies to recomputation and reuse under the same
current helper, owner paths and template. Against the older archive, vectors,
configuration, source manifests, projections and dispositions remained exact;
recipe, job and plan identities legitimately differ because the current helper,
new owner paths and template identities are bound into those artifacts.

This was a preparation experiment: one probe process, 47 stored samples, bridge
names `[]`, prover evaluation `false`, metric disk-cache flag `0`, and no dispatched
training workers or bridge evaluate. No legal-IR target count or wall time per
compiler span was produced. Priming and uncontrolled OS cache state preclude a
cold-run claim. No inference, model checkpoint loading, bridge evaluation,
training dispatch, live Quack or Hugging Face operation ran in the probe.

The [complete audit](../../../workspace/test-logs/federal-corpus-audits/campaign-root-reuse-20260926/capture-r1/audit-receipt.json)
took 442.089775 seconds against a 600-second bound. All 7,762 package Python
files, 906 dependency files, four frozen harness files, archived inputs and
protected artifacts remained unchanged at the guarded boundaries. The compiler,
decompiler and parser resolved to the canonical workspace tree. Network-denial
rules were installed before package imports. All 15 prior retained claim rows
were preserved; unsuccessful historical attempts were not reclassified.

The reservation covered one CPU slot, 1,024 MiB RAM and 700,000,000 disk bytes,
including a full 500,000,000-byte external fixture charge. Successful fixtures
were removed only under this capture's named temporary root; prior failed
fixtures remained preserved. The probe's lifetime high-water RSS was 782,987,264
bytes. It includes setup, priming, all modes and parity checks, so it establishes
neither per-mode peaks nor a memory improvement.

The [resource receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-root-reuse-20260926/capture-r1/resource-release.json)
records 109,735,573 final owned bytes and 609,735,573 total charged bytes.
Reservation `e8bca41408714d3eaa842a9cb5d94376` and scheduler lease
`a08148bfe8504783ae7eea7469ba60f7` were released with no live owned child.
Enforcement was cooperative with sampled process-group and disk checks.

The [independent standard-library closeout](evidence/autoencoder_control_plane_plan/campaign-root-reuse-closeout-20260926-r2.json)
passed all 47 checks with no diagnostics. It reconstructed recipe, job and plan
identities, exact vectors/manifests/projections and all 62,839 dispositions;
recomputed the comparison statistics; and checked current source, dependency,
harness and artifact bytes, released resources, dead child groups and retained
claims. It opened no database: captured registry records are evidence from the
guarded run, not a new owner-state query.

The first [closeout receipt](evidence/autoencoder_control_plane_plan/campaign-root-reuse-closeout-20260926-r1.json)
is retained as failed: its command-line assertion expected the original pytest
arguments, while pytest had prepended the exact options from the guarded
`pytest.ini`. The other 44 checks passed. The successful revised checker derives
that exact prefix from the guarded configuration and verifies preservation of
the failed receipt and script. No tests or performance observations were rerun,
and their source/harness revision did not change.

## Opportunity cost and remaining work

The expected benefit is avoiding repeated construction of a large immutable
metadata graph. The cost is extra private lifecycle and drift-checking code,
repeated source/root hashing, and retaining the root graph through plan sealing.
Dropping duplicate upstream graphs can reduce retention, but longer scope
lifetime can increase memory relative to releasing roots before sealing. Memory
must be observed; fewer decodes do not prove lower peak RSS. The 23.66 MB
exhaustive generation manifest still incurs serialization and temporary-write
cost, and selected leaves and sources still receive fresh verification.
Process high-water RSS covers the probe's complete lifetime, including setup,
priming, comparisons and verification. It cannot establish a phase-only peak
or assign a separate peak to A and B. Sampled process-group observations and
cooperative resource admission are not continuous peak measurement or kernel
quotas.

The bounded comparison supports retaining this narrow preparation optimization
with the exact parity and resource scope above. Profile the remaining
complete-call cost before adding further cache layers, changing
Arrow defaults or increasing worker count. It cannot create missing embeddings,
cover newly generated samples with an incomplete target bundle, or improve legal
semantics by itself.

The [offline publication plan](autoencoder_campaign_publication_plan.md) remains
the complementary next deliverable: a selected-page package with template,
job, source, target and checkpoint dependency closure and exact evidence-only
restore. Full-source campaign packaging, executable path rebinding, the owned
Quack plan adapter, native qualification, production DuckLake activation and
Hugging Face upload remain separate work. No live service or publication is part
of this change.

Related plans are the [DuckDB/DuckLake training plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md)
and [federal-law end-to-end plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
The Constitution remains unformalized. A source row, decompiled sentence,
autoencoder result or preparation receipt is not an admit; only
`lake build <Lib>` counts as a Lean admit.
