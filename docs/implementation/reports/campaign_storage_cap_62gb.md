# Campaign storage cap: 62 GB and full-source validation outcome

The user authorized a campaign cap of **62,000,000,000 bytes** on 2026-09-27.
The explicit migration changed only the ledger's top-level limit under its
existing lock. All 75 historical reservation records (29 retained, 46 released)
and root identities were preserved. The per-worker **50 GB** limit, failed
claims, pinned restart12 checkpoint, and live Git HEAD/index were unchanged.
The controller still rejects older ledgers; it does not migrate or release them
implicitly. See the [migration receipt](evidence/autoencoder_control_plane_plan/campaign-cap-62gb-migration-20260927.json).

All five selected resource tests passed, with no failures, errors or skips:
the new default, rejection of unmigrated 50 GB/60 GB ledgers, and explicit
top-level migration preserving historical records and full accounting for both
old limits. The guarded pytest call took 0.273733 seconds; its source, dependency,
input and protected-artifact checks passed. This was the cap-test phase only;
it did not rerun or replace the earlier 132-case entity/semantic qualification.
See the [test receipt](evidence/autoencoder_control_plane_plan/campaign-cap-62gb-tests-20260927.json)
and [JUnit results](evidence/autoencoder_control_plane_plan/campaign-cap-62gb-tests-20260927.xml).

The subsequent full-source validation **failed**. It used the existing local
180,257-entity and 120,136-relationship Parquet inputs, a new isolated cache,
one CPU, a 1 GiB child-group RSS bound, a 750 MB storage reservation, and a
1,200-second deadline. The pre-admission source/dependency quiet gate passed.
The parent stopped its owned child group after observing **1,159,016,448 bytes**
RSS against the **1,073,741,824-byte** limit. The audit ended after 300.932 seconds;
owned artifact bytes at the failing check were 292,442,066, plus a conservative
2,000,000-byte external fixture charge. No memory or per-worker cap was raised.
The [failed audit](evidence/autoencoder_control_plane_plan/entity-v2-full-source-failed-audit-20260927-r1.json)
is retained unchanged.

The child log also records a harness `JSONDecodeError`: the normal pinned-tree
diagnostic precedes the CLI JSON report, while the harness expected the entire
stdout string to be JSON. The independent original-source readback, snapshot
comparison and reopened self-observation had not started. Both this error and
the RSS failure require repair; neither can be reclassified as a passing run.
The [original source log](evidence/autoencoder_control_plane_plan/entity-v2-full-source-failed-source-20260927-r1.log)
records these partial wall times:

| Completed CLI phase in the failed run | Seconds |
| --- | ---: |
| Resume ingestion after the 1,536-row prefix | 16.685 |
| Containment preparation | 84.656 |
| Snapshot export with production validation | 111.283 |
| CLI total, including the above phases | 212.842 |

These are partial source-I/O observations with uncontrolled filesystem caches.
The rows are entities, not legal spans. No bridge-on evaluate ran; bridge names,
prover flag, metric cache and bridge worker count are inapplicable. These times
do not establish an end-to-end speedup, successful full-source qualification,
training throughput, or a legal-IR measurement.

The fresh failed 750 MB claim remains retained, all earlier 75 claims remain
byte-equivalent as records, and the owned process group was confirmed dead.
See the [post-failure observation](evidence/autoencoder_control_plane_plan/campaign-cap-62gb-postfailure-20260927.json).
The original DB, snapshot, harness, source/dependency captures and failed receipt
remain under `workspace/test-logs/federal-corpus-audits/entity-v2-full-source-20260927/`.
No second full-source copy was started in this cap change. Next work is to fix
bounded CLI report decoding and qualify bounded Parquet row groups and reader
lifetimes before a fresh capacity-admitted comparison; no allocation or speed
improvement is claimed from static inspection alone.

Native model/checkpoint/training validation and Hub uploads remain deferred.
There were no model downloads, model runs, external provers, or Lake executions.
The Constitution remains unformalized. Only `lake build <Lib>` is a Lean admit.
