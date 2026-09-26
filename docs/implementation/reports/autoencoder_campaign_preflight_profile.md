# Campaign preparation diagnostic profile

The bounded offline profile completed on 2026-09-26 and released its resource
reservation. It profiled exactly one fresh v8 metadata preparation and exactly
one consumption of the resulting prepared context, using the archived six-record
job in place: three training records and three validation records. Returned
verification matched the prior passed capture exactly. No registry, model,
training, inference, bridge evaluation or publication was involved.

| Diagnostic | Observed value |
|---|---:|
| Profiled metadata preflight | 10.706867196 seconds |
| Profiled prepared verification | 0.534310981 seconds |
| Complete guarded audit | 28.408864346 seconds |
| Process lifetime high-water RSS | 447,561,728 bytes |
| Final owned attempt storage | 5,489,820 bytes |

The RSS figure is Linux `ru_maxrss` converted to bytes. It is a lifetime process
high-water mark, not PSS or a peak attributed exclusively to either phase. The
reservation bounded disk at 50 MB, memory at 896 MiB, one CPU slot and elapsed
time at 90 seconds. The release receipt reports no live owned processes.

The three top-level campaign loaders each ran once. Existing nested validation
still constructed the inventory three times and the partition object twice;
the grouping assignment routine also ran twice. This explains why the previous
same-operation reuse did not eliminate whole-campaign setup. The profile records
25,016,486 calls during preparation and 1,712,300 during prepared verification.
JSON normalization and nested inventory/partition validation dominate the
preparation call tree. Cumulative times overlap and must not be added together.

These are instrumented diagnostic timings, not a new training speed baseline
or a comparison with unprofiled historical timings. The run used one worker,
bridge names `[]`, prover evaluation `false`, and metric disk-cache flag `0`.
OS page-cache state was uncontrolled; no cold-cache claim is made. The run
did not measure wall time per legal span or a bridge-on evaluate.

All 7,759 package source files matched across parent and child capture points.
The harness, exact archived input closure, protected artifacts and previously
retained failed claims also passed their guards. This qualifies the captured
revision during that run only; subsequent implementation edits require their
own capture. The prior failed audits remain failed and their claims remain
retained.

This diagnostic motivated the subsequent
[campaign workflow integration](autoencoder_campaign_workflow.md), which connects
v8 inputs to the existing training cycle and verifies their combination with
shared targets, sparse updates and optional Arrow feature weights. Its separate
offline capture passes. Connecting these pieces tests their provenance
boundaries before spending more effort on a broader metadata cache.
This profile identifies an optimization opportunity; it does
not establish that persistent caching is the highest-value next change. Any
future cache would still need exact source bindings, role authorization and
fresh selected-byte checks.

Evidence: [audit receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-preflight-profile-20260926/profile-r1/audit-receipt.json),
[profile report](../../../workspace/test-logs/federal-corpus-audits/campaign-preflight-profile-20260926/profile-r1/profile/profile-report.json),
[preflight pstats](../../../workspace/test-logs/federal-corpus-audits/campaign-preflight-profile-20260926/profile-r1/profile/preflight.pstats),
[verification pstats](../../../workspace/test-logs/federal-corpus-audits/campaign-preflight-profile-20260926/profile-r1/profile/verification.pstats),
and [resource release](../../../workspace/test-logs/federal-corpus-audits/campaign-preflight-profile-20260926/profile-r1/resource-release.json).
Related work: [prepared-context reuse](autoencoder_prepared_campaign_inputs.md),
[campaign jobs](autoencoder_campaign_training_jobs.md),
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md), and
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

Native checkpoint qualification remains deferred. These checks establish no
source authority, new global holdout claim or Lean admit. Lake remains the only
admit path. The Constitution remains unformalized.
