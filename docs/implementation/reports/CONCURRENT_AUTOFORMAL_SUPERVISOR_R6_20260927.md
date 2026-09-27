# Concurrent autoformal supervisor smoke R6 — 2026-09-27

The last bounded retry ran all **nine optimizer attempts** across three update families while compiler/decompiler checks executed concurrently. The measured overlap was **29.410825368 seconds**. Accepted epochs remained **0**: six proposals regressed legal-IR validation metrics and three produced no objective improvement. The overall smoke correctly **failed**, with strict rollback and all other parent-harness checks passing. [Parent receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/smoke-receipt.json), [full native training receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/training/native/receipt.json).

## Search expansion and unchanged conditions

R6 raised `projection_max_update_families` and `max_line_search_attempts` from 1 to 3 and added the `-r6` job/run ID suffix. A structural comparison verifies those are the only four changed configuration fields. The data, protected restart12 base checkpoint, objectives, acceptance limits, one epoch, 180-second training budget, bridge names/flags, and Python backend were unchanged. [Change record](evidence/concurrent-autoformal-supervisor-r6-20260927/r6-search-expansion/change.json), [before configuration](evidence/concurrent-autoformal-supervisor-r6-20260927/r6-search-expansion/frozen-config.before.json), [exact executed configuration](evidence/concurrent-autoformal-supervisor-r6-20260927/r6-search-expansion/frozen-config.after.json), and [verified diff](evidence/concurrent-autoformal-supervisor-r6-20260927/r6-search-expansion/verified-config-diff.json).

The before/after configuration hashes are `59a95d61118d91325e9071e1ef441b861dbf8a44105b6141ee3d4ef3b7696ffe` and `2b828d157e4115bbd527904d42c758e3b84b404e32efc52cfe476131ba083ca7`. The original change record's `native_r6_executed=false` is preserved as a pre-run preparation observation; the actual execution receipts below establish what subsequently ran. The executed configuration also matches the prepared configuration byte-for-byte.

The accelerator was explicitly bound to source commit `7adfbfc548baaaf7ca86cf70b18ec7effb71ad82` and exported snapshot `aa873b3e47e68bf14bcda55e5a972ec6b37671f3`. The datasets compiler/decompiler/parser remained pinned to `/home/barberb/lift_coding/external/ipfs_datasets`. Source, harness, input, and checkpoint guards passed. The protected checkpoint retained SHA256 `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`. [Prepared input identities](evidence/concurrent-autoformal-supervisor-r6-20260927/prepared-inputs.json), [child source receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/child-source-receipt.json).

## Actual execution and rejection

The real embedded single-owner DuckDB supervisor selected/claimed the private task and executed its deterministic validation plan. Both lanes exited zero. The accepted-update assertion failed; native settlement then marked the task blocked and released its claim. Provider invocations and effect claims were both **0**. The generic `portal_provider_failed` settlement label records this deterministic validation failure; it is not evidence of an external provider invocation. Live Quack transport was not exercised. [Supervisor receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/supervisor-receipt.json), [Portal events](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/state/smoke_database_portal_attempts/21ce89e0388ce54504c06b1f/portal-events.jsonl).

| Timing scope | Wall seconds |
| --- | ---: |
| Outer wrapper | 230.875171 |
| Native child | 230.471841 |
| Supervisor method | 207.040503 |
| Parent concurrent harness | 162.046837 |
| Training worker | 125.511183 |
| Native projection training | 116.275062 |
| Conversion interval | 29.410825 |
| Exact training-method/conversion overlap | 29.410825 |

The lanes used distinct CPUs. The overlap is derived from monotonic conversion timestamps and entry/return monitoring of the unmodified training method, not merely concurrent process lifetimes.

Three synthetic training gates and two distinct synthetic acceptance fixtures were used; their sample IDs and normalized text hashes did not overlap. The acceptance fixtures were repeatedly consulted by line search, so they are **not an untouched held-out canary**. `heldout_canary_qualified=false`. All nine attempts completed within the unchanged 180-second training budget; `stopped_reason=null`.

| Update family | Attempt | Effective learning rate | Validation view CE worsening | Outcome |
| --- | ---: | ---: | ---: | --- |
| `legal_ir_view_global_logits` | 1 | 0.17500 | 0.173599685 | IR regressions; rejected |
| `legal_ir_view_global_logits` | 2 | 0.08750 | 0.177851216 | IR regressions; rejected |
| `legal_ir_view_global_logits` | 3 | 0.04375 | 0.180058490 | IR regressions; rejected |
| `legal_ir_view_logits` | 1 | 0.17500 | 0.172527089 | IR regressions; rejected |
| `legal_ir_view_logits` | 2 | 0.08750 | 0.177287203 | IR regressions; rejected |
| `legal_ir_view_logits` | 3 | 0.04375 | 0.179769337 | IR regressions; rejected |
| `family_logits` | 1 | 0.35000 | -0.000000000 | Zero objective gain; rejected |
| `family_logits` | 2 | 0.17500 | -0.000000000 | Zero objective gain; rejected |
| `family_logits` | 3 | 0.08750 | -0.000000000 | Zero objective gain; rejected |

Positive worsening above is `after - before`; the raw trainer delta uses `before - after`. Legal-IR guardrails and strict acceptance were unchanged and deadband remained off. Each proposal was rejected; base and candidate component digests and normalized state identity are exactly equal after rollback. Final validation metrics equal this run's baseline. The [sparse candidate manifest](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/training/native/candidate.manifest.json) has no patches, revision 0, and zero accepted patch bytes; no complete candidate checkpoint was written or promoted.

## Bridge timings and interpretation

All 11 evaluations ran the same five bridges: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`. Flags were `legal_ir_evaluate_provers=false`, `legal_ir_parallel_workers=1`, `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`, and `use_sample_memory=false`. The process target cache began empty. Disk metric caching stayed off, process caches warmed during this job, and OS cache state was uncontrolled. [Exact evaluate timing receipts](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/training/evaluate-timings.json).

| Bridge-on evaluate | Samples | Legal-IR targets | Wall seconds | Seconds per span | Cache condition |
| --- | ---: | ---: | ---: | ---: | --- |
| 0 — Initial acceptance validation | 2 | 2 | 62.814495 | 31.407248 | Initially empty process target cache |
| 1 — Training-target evaluation | 3 | 3 | 15.564080 | 5.188027 | First use of training rows; initialized process |
| 2 — Candidate validation 1 | 2 | 2 | 0.517205 | 0.258602 | Process-warm validation targets |
| 3 — Candidate validation 2 | 2 | 2 | 1.810833 | 0.905417 | Process-warm validation targets |
| 4 — Candidate validation 3 | 2 | 2 | 0.525857 | 0.262929 | Process-warm validation targets |
| 5 — Candidate validation 4 | 2 | 2 | 0.572460 | 0.286230 | Process-warm validation targets |
| 6 — Candidate validation 5 | 2 | 2 | 0.547313 | 0.273657 | Process-warm validation targets |
| 7 — Candidate validation 6 | 2 | 2 | 0.796847 | 0.398424 | Process-warm validation targets |
| 8 — Candidate validation 7 | 2 | 2 | 2.304422 | 1.152211 | Process-warm validation targets |
| 9 — Candidate validation 8 | 2 | 2 | 0.562350 | 0.281175 | Process-warm validation targets |
| 10 — Candidate validation 9 | 2 | 2 | 0.674910 | 0.337455 | Process-warm validation targets |

The profile records **24.333459 seconds** across nine projection update batches, including a largest batch of **16.272787 seconds**. Feature-head work within those batches totals 24.332782 seconds and overlaps that accounting; it must not be added again. Initial validation took 62.814573 seconds, training-target cache preparation 15.564188 seconds, and nine acceptance evaluations totaled 8.312962 seconds. R6 exercised more expensive update families than R5; the profile does not establish a CUDA benefit or justify switching the backend. ErgoAI resolution/installation-attempt log messages are initialization telemetry, not proof or prover evaluation. [Training log](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/training.log).

These are **not like-for-like speed or accuracy comparisons** with R5, the full Constitution, or earlier measurements. In addition to the expanded search, R6's initial acceptance baseline itself differed: legal-IR view CE was 1.609437912434 and deontic IR cosine was 0.959788824395, versus R5's 1.700598690831 and 0.977704136350. The unchanged configured inputs do not establish identical generated targets or runtime/cache conditions; this report does not attribute that difference to a cause. No improvement is inferred from the lower baseline CE or shorter outer wall time.

The next priority is to capture and compare per-sample target payloads and bridge diagnostics in immutable shared-target snapshots, then replay them against the same checkpoint and validation split before further weight tuning. That would help separate target-generation differences from optimizer behavior; it is a proposed follow-up, not a finding about the cause of this baseline difference.

R6 still used `weight_storage="private_json"`, `shared_targets_verified=false`, and `shared_target_count=0`; Arrow weight artifacts/statistics were absent. Sparse output was configured, but all attempts rolled back and zero sparse segments were accepted. This does not qualify shared-target reuse, Arrow-backed weights, accepted sparse updates, or parallel training by multiple weight writers.

## Conversion evidence

All synthetic semantic gates and empty-vocabulary abstention passed, including deadline/exception preservation, prohibition, minimum-duration quantity 20, and non-renderability of `within_duration` as a Lean threshold. Synthetic gate wall times were **28.837081**, **0.280607**, and **0.102737 seconds** respectively (mean **9.740142 seconds per span**). These observed times include the first case's initialization/runtime effects; no causal breakdown or speedup is claimed. [Conversion receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/supervisor/lanes/conversion/summary.json).

The same three retained US Code spans were processed with parser vocabulary and `allow_partial=false`; each abstained on unsupported cross-reference/override semantics. Source and gap evidence were retained. Mean real-span processing time was **0.045210 seconds per span**, not a successful formalization rate.

| Retained source | Vocabulary seconds | Compiler seconds | Total seconds per span | Status |
| --- | ---: | ---: | ---: | --- |
| 7 U.S.C. § 2006d | 0.022649 | 0.026992 | 0.049642 | Abstained |
| 5 U.S.C. § 8410 | 0.021837 | 0.027726 | 0.049564 | Abstained |
| 16 U.S.C. § 6809 | 0.015442 | 0.020981 | 0.036424 | Abstained |

Compiler/decompiler checks are not compiler/decompiler training. No Constitution span was processed or marked roundtrip_ok; the Constitution remains unformalized. Lake was not executed, and no legal admission is claimed.

## Resource retention

The wrapper retained its 600-second deadline, two CPU slots, 8 GiB memory budget, 150 MB owned-output bound, and authorized 75 GB campaign cap. Enforcement used cooperative admission and polled RSS/storage with Linux subreaper PID/birth custody, not a kernel disk quota. Peak sampled descendant RSS was **1,522,843,648 bytes**. The audit records all **8** tracked owned descendants and the child process group dead; cleanup reported no error. [Outer audit](evidence/concurrent-autoformal-supervisor-r6-20260927/audit-receipt.json).

Reservation **`46b02aabb1f44f769143755554857d79` remains retained at 150,000,000 bytes**, with the compute resource lease released. Last polled attempt size was **40,007,630 bytes**. A post-exit observation counted **49,515,484 apparent bytes across 116 regular non-symlink files**, including the locally retained DuckDB binaries. These are distinct observations; the smaller live sample is not the closed-runtime size. [Retention receipt](evidence/concurrent-autoformal-supervisor-r6-20260927/resource-retention.json), [post-exit observation](evidence/concurrent-autoformal-supervisor-r6-20260927/observation.json).

The evidence bundle preserves exact outer/child/supervisor/Portal/parent/training/conversion receipts, full metrics, all failed optimizer attempts, sparse candidate manifest, configuration-change provenance, and logs. DuckDB binaries remain in the retained capture and are excluded from this export. This report covers R6 only: no further retry, successful optimizer update, native smoke pass, Hugging Face upload, production promotion, or formalization is claimed.
