# Concurrent autoformal supervisor smoke R5 — 2026-09-27

R5 ran the real deterministic supervisor lifecycle, native autoencoder training, and compiler/decompiler checks with **1.317367501 seconds of verified overlap**. The overall smoke **failed** because its single optimizer proposal worsened the separate synthetic acceptance-validation metrics and was rejected. All other parent-harness checks passed. Strict acceptance and rollback remained active; no model promotion or legal admission occurred. See the [parent smoke receipt](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/smoke-receipt.json) and [supervisor receipt](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/supervisor-receipt.json).

## Execution and provenance

This run used accelerator source commit `7adfbfc548baaaf7ca86cf70b18ec7effb71ad82`, explicitly exported as snapshot `aa873b3e47e68bf14bcda55e5a972ec6b37671f3`. The canonical compiler, decompiler, and parser remained pinned to `/home/barberb/lift_coding/external/ipfs_datasets`. Both source trees, the frozen harness, external conversion inputs, and protected restart12 checkpoint passed their before/after guards. The checkpoint retained SHA256 `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`. [Child provenance](evidence/concurrent-autoformal-supervisor-r5-20260927/child-source-receipt.json) and [prepared inputs](evidence/concurrent-autoformal-supervisor-r5-20260927/prepared-inputs.json) preserve the identities.

The supervisor selected and claimed the private smoke task, recorded protected paths, authorized its deterministic validation plan, and executed the actual local validation command. Both lanes exited zero. The failed accepted-update assertion then caused native failure settlement: task `blocked`, claim `released`, provider invocations **0**, effect claims **0**. The generic `portal_provider_failed` reason in the settlement does not mean an external provider ran; [Portal events](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/state/smoke_database_portal_attempts/6963ffde015a04951c4d443e/portal-events.jsonl) and the full supervisor receipt record the underlying failed deterministic validation. The embedded single-owner DuckDB authority was exercised; live Quack transport was not.

| Timing scope | Wall seconds |
| --- | ---: |
| Outer resource wrapper | 270.184724 |
| Native child | 269.792012 |
| Supervisor method | 210.952343 |
| Parent concurrent harness | 169.484718 |
| Training worker | 105.286789 |
| Native projection training | 89.652259 |
| Conversion measured interval | 1.317368 |
| Exact training-method/conversion overlap | 1.317368 |

The lanes ran on distinct CPUs. Overlap uses local monotonic timestamps at entry/return of the unmodified `train_generalizable_projection` method and conversion start/finish, rather than process lifetime alone.

## Training result and bridge timings

Training used three synthetic gate sentences and two distinct synthetic acceptance-validation fixtures. No sample IDs or normalized text hashes overlapped these splits. Those two fixtures were consulted for acceptance; they are **not an untouched held-out canary**, and `heldout_canary_qualified=false`.

The run used one epoch, one update family (`legal_ir_view_global_logits`), one line-search attempt, a 180-second training budget, `python_sparse_batch`, configured learning rate 0.35 and effective head learning rate 0.175. The actual proposal had finite nonzero gradient norm 0.273424218842 and update norm 0.047849238297, covering six scalar logits. Its validation legal-IR view cross-entropy worsened from **1.700598690831 to 1.785381348342**, a regression of **0.084782657511**; family cosine gap worsened by 0.034337653267 and frame-logic excess cross-entropy by 0.091333225529. Strict Pareto/IR guardrails rejected it, with deadband disabled. Accepted epochs: **0**. The reported negative delta uses the trainer's before-minus-after convention; it is a regression, not an improvement. [Full native receipt](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/training/native/receipt.json).

Rollback restored the original component digests and normalized state identity exactly. Final acceptance metrics equal baseline. The sparse candidate manifest contains `patches=[]`, revision 0, and no accepted patch bytes; it is not an accepted trained checkpoint. A complete candidate checkpoint was not written. [Candidate manifest](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/training/native/candidate.manifest.json).

All three evaluations used the same five bridges: `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`. Each ran with `legal_ir_evaluate_provers=false`, `legal_ir_parallel_workers=1`, `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`, and `use_sample_memory=false`. The process target cache started empty. Disk metric caching was disabled throughout; process caches warmed within this job and OS cache state was uncontrolled. [Exact evaluate timings](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/training/evaluate-timings.json).

| Bridge-on evaluate | Samples | Legal-IR targets | Wall seconds | Seconds per span | Cache condition |
| --- | ---: | ---: | ---: | ---: | --- |
| Initial acceptance-validation evaluation | 2 | 2 | 74.481092 | 37.240546 | First evaluation; process target cache initially empty |
| Training-target evaluation | 3 | 3 | 14.490279 | 4.830093 | First evaluation of these training rows; process already initialized |
| Candidate acceptance evaluation | 2 | 2 | 0.534516 | 0.267258 | Same validation targets, process-warm |

No bridge-off pass is counted as a legal-IR timing. ErgoAI resolution/installation-attempt messages in the [training log](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/training.log) are initialization telemetry, not prover evaluation or proof. The profile attributes **0.134542 seconds** to the projection update batch, versus approximately **89.506 seconds** to the evaluation/cache-preparation stages. This profile provides no justification for switching to CUDA.

This run used `weight_storage="private_json"`, `shared_targets_verified=false`, `shared_target_count=0`, and no Arrow weight artifact or Arrow feature statistics. Sparse candidate storage was selected, but rollback left zero accepted sparse segments. It therefore does **not** qualify shared-target reuse, Arrow-backed weights, an accepted sparse update, or parallel training across multiple weight writers.

## Compiler/decompiler and source spans

The conversion lane passed all three synthetic semantic gates, preserved deadline/exception text, kept the prohibition, preserved `minimum_duration` quantity 20, and confirmed empty-vocabulary abstention. The within-duration case remained non-renderable as a Lean threshold. Lake was not executed. [Full conversion evidence](evidence/concurrent-autoformal-supervisor-r5-20260927/supervisor/lanes/conversion/summary.json).

| Synthetic gate | Result | Wall seconds per span |
| --- | --- | ---: |
| Company A backup report, within 10 days unless emergency | Compiled/roundtripped; obligation and `within_duration` preserved | 0.821602 |
| Agency shall not disclose records | Compiled/roundtripped; prohibition preserved | 0.100115 |
| Officer retains file for at least 20 days | Compiled/roundtripped; minimum duration and quantity preserved | 0.106120 |

Three retained US Code spans were processed with parser-supplied vocabulary and `allow_partial=false`. All three abstained on unsupported semantics, preserving their source identifiers and diagnostic evidence. Their mean measured wall time was **0.074769 seconds per span**. This is abstention-processing time, not evidence that these provisions were formalized.

| Retained source | Vocabulary seconds | Compiler seconds | Total seconds per span | Preserved gap |
| --- | ---: | ---: | ---: | --- |
| 7 U.S.C. § 2006d | 0.023145 | 0.026726 | 0.049872 | Cross-reference semantics |
| 5 U.S.C. § 8410 | 0.021810 | 0.027499 | 0.049310 | Override/cross-reference semantics |
| 16 U.S.C. § 6809 | 0.015024 | 0.110099 | 0.125124 | Cross-reference semantics |

These small, different samples are not a like-for-like speed comparison with the full Constitution or prior three-sentence bridge measurements. Compiler/decompiler checks are not compiler/decompiler training. No Constitution span was processed or marked roundtrip_ok here; the Constitution remains unformalized.

## Resource retention and evidence

The wrapper enforced a 600-second deadline, two CPU slots, 8 GiB memory budget, and 150 MB owned-output bound under the authorized 75 GB campaign cap. Enforcement used cooperative admission and polled storage/RSS with Linux subreaper PID/birth custody; it was not a kernel disk quota. Peak sampled descendant RSS was **1,552,179,200 bytes**. The outer audit records all **13** owned descendant identities dead and the child process group dead; cleanup reported no error. [Outer audit](evidence/concurrent-autoformal-supervisor-r5-20260927/audit-receipt.json).

Reservation **`77dedd5a6cea41eab960b9f5c67d6bb6` remains retained at 150,000,000 bytes**; the resource lease was released. Last polled attempt size was 39,874,517 bytes. A separate post-exit observation counted **49,374,312 apparent bytes across 116 regular non-symlink files**, including locally retained DuckDB files. The latter is the post-close size, not the earlier sample. [Retention receipt](evidence/concurrent-autoformal-supervisor-r5-20260927/resource-retention.json) and [post-exit observation](evidence/concurrent-autoformal-supervisor-r5-20260927/observation.json).

The evidence directory contains exact outer/child/supervisor/Portal/parent/training/conversion receipts, full metrics, sparse candidate manifest, input identities, and logs, with a hash manifest. DuckDB binaries remain in the retained runtime and are excluded from this export. No Hugging Face upload, production promotion, successful optimizer update, native smoke pass, or Lake admission is claimed. This report covers R5 only.
