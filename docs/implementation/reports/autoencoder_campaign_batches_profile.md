# Campaign batch preparation profile

The guarded offline retry on 2026-09-26 passed. One preparation call took
67.286434 seconds with direct timing instrumentation. Its three shared root
loaders accounted for 60.435699 seconds, or 89.82% of that wall time. Each root
was loaded eight times. This identified repeated metadata validation as the
preparation optimization implemented in the later
[root-reuse report](autoencoder_campaign_root_reuse.md); the profile itself
establishes no training speedup.

The profile uses the same archived data as the
[batch-generation qualification](autoencoder_campaign_batches.md): 40 training
records and seven shared validation records, arranged into three jobs with
16, 16 and eight training records. There are 47 unique selected records and
61 occurrences across the jobs. Four embedded holdout records remain excluded;
13 token-limit failures and 62,775 unattempted unique inputs remain visible in
the full 62,839-input denominator. No new extraction or embedding inference ran.

An isolated DuckDB registry used the archived three-byte synthetic checkpoint
fixture, not model weights. Original vectors, ordered roles, configuration,
manifest and projection identities, selected artifacts and every input
disposition matched the passed archive. New owner paths and template IDs
necessarily produced new recipe, job and plan identities. All generated runs
remained queued, with the template run and checkpoint head unchanged.

## Measured work

| Original operation | Calls | Inclusive wall seconds |
|---|---:|---:|
| Load source inventory | 8 | 9.583166 |
| Load source partitions | 8 | 24.346180 |
| Load embedding receipt set | 8 | 26.506353 |
| Verify registered template | 1 | 7.880584 |
| Direct generated-job verification | 3 | 24.322052 |
| Seal plan, including registered-job verification | 1 | 24.684386 |
| Build produced-record projections | 3 | 0.690583 |
| Stage CAS artifacts | 59 | 0.466732 |
| Verify CAS artifacts | 411 | 0.315309 |
| Rehash selected source/receipt closure | 68 | 0.026428 |

The three root-loader categories are distinct calls and can be added to obtain
60.435699 seconds. They are nested within template, job and plan phases, so the
entire table must not be summed. Nested codec reconstruction produced 24
inventory, 16 partition and eight receipt-set constructor calls. Those
constructor durations overlap their loaders and each other.

The eight root triplets come from one template verification, one direct
generator load, three generated-job verifications and three plan verifications.
Each triplet retains the codecs' existing nested validation. The low staging
time in this fixture gives no reason to change storage backends before removing
repeated decoding. This is an inference about this preparation path, not a
comparison of DuckDB, Quack, DuckLake or Arrow during weight updates.

The [phase observations](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-profile-retry-20260926/profile-r2/profile/phase-observations.json)
record counts, inclusive wall times and call edges. Each wrapper calls the
captured original once and restores it afterward. Stack-exclusive times
subtract only other instrumented children; they are not Python self time.
Complete `final_inputs` wall time and call count were not separately measured.
Artifact verification and rehash totals include those checks among other calls.

The [profile report](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-profile-retry-20260926/profile-r2/profile/profile-report.json)
records one process (`worker_count=1`, with no training workers dispatched),
47 stored samples, bridge names `[]`, prover flag `false` and metric disk-cache
flag `0`. No bridge evaluate ran and no legal-IR target count was produced.
OS cache state was uncontrolled; this is not a cold-run claim. Timing wrappers
add overhead, and there is no uninstrumented comparison or speed ratio.
These are not per-span compiler or bridge-on evaluation timings.

## Provenance and resource boundaries

The [complete audit](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-profile-retry-20260926/profile-r2/audit-receipt.json)
took 86.594706 seconds against a 300-second bound. All 7,762 package Python files,
905 dependency files, three frozen harness files, archived inputs and protected
artifacts remained unchanged across the parent and child boundaries. The
compiler, decompiler and parser resolved to the canonical workspace tree.
Network-denial seccomp rules were installed before package imports.

The reservation covered 180,000,000 disk bytes, 1,024 MiB RAM and one CPU slot.
Final owned storage was 108,265,958 bytes. Lifetime process high-water RSS was
763,420,672 bytes, including setup and parity checking; this is not a phase-only
peak or PSS measurement. Enforcement uses cooperative admission and sampled
process-group/disk checks, not a kernel quota.

The [resource receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-profile-retry-20260926/profile-r2/resource-release.json)
records release of reservation `3806df31ddca4ebcab0ef074ffaa7472` and scheduler
lease `b3be8e458ade4cf9bd9864bbe233d517`, with no live owned child. All 15 prior
retained claim rows were unchanged. No pytest fixtures were created.

An earlier [cProfile attempt](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-profile-20260926/profile-r1/audit-receipt.json)
failed during harness postprocessing because its statistics omitted required
outer function entries. Its final provenance checks did not complete, so its
timing remains unqualified. The cause of the missing profiler records was not
established. The retry uses direct wrappers without cProfile or caller-frame
inspection. The failed attempt's code, log, raw profile and unsuccessful audit
are pinned, and its 180,000,000-byte reservation
`05a2312e42c545b492f4932490dc58b6` remains retained. No historical result was
reclassified or overwritten.

The [independent standard-library closeout](evidence/autoencoder_control_plane_plan/campaign-batches-profile-closeout-20260926-r2.json)
passed all 33 checks. It reconstructed recipe, job and plan identities, compared
the exact archived data contracts and full dispositions, and verified timing
edge accounting, current source/dependency/artifact bytes, resource release,
the dead child process group and all prior retained claim rows. It opened no
database and treated captured registry records as capture evidence, not a new
query of owner state. No tests or native validation were added by this profile.

## Implemented follow-up

The [operation-local root reuse](autoencoder_campaign_root_reuse.md) follow-up
now retains one decoded root graph within a bounded preparation call. It binds
exact paths, hashes, sizes, limits, owner CAS, thread and loader/code identity,
and invalidates on exit or failure. First-load nested codec validation remains
intact. Every job still gets an exact-spec, single-use prepared context, complete
role and membership checks, fresh metadata and selected-byte checks, and final
registration barriers. Independent public worker/owner entrypoints load fresh
roots. No persistent or receipt-leaf cache was added.

All 682 offline tests passed, including 49 new cases for those boundaries and
synthetic eight-to-one loader-count assertions. A separate uninstrumented,
guarded A/B/B/A comparison used the same current validators and a primed owner
page: repeated preparation medians were 66.324950 seconds with recomputation
and 15.117741 seconds with reuse (4.387226×, two observations per mode). Exact
current artifacts, archived data contracts and queued state were preserved.
These are new preparation results, not a ratio against this instrumented
historical profile, first-registration throughput or an optimizer improvement.
All 47 [independent closeout checks](evidence/autoencoder_control_plane_plan/campaign-root-reuse-closeout-20260926-r2.json)
passed. The new report includes every observation and lifetime-only memory
qualification.

In parallel, the [offline publication design](autoencoder_campaign_publication_plan.md)
defines selected-page packaging, exact dependency closure and evidence-only
restore. It remains a proposal. Shared-target runtime membership, native
checkpoint qualification, live Quack/DuckLake activation and remote publication
remain separate work. The Constitution remains unformalized, and only
`lake build <Lib>` counts as a Lean admit.
