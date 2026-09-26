# Resume-checkpoint observations and shared supervisor status

Integration scope, 2026-09-26. This follows the
[owned worker execution capture](autoencoder_campaign_owned_execution.md) and
reviews the additional Grok changes found before main-branch publication. The
focused supplemental capture passed all 36 checks with no failures, errors or
skips. Native checkpoint validation remains deferred.

The resume parquet format contains status summaries and agent observations. It
does not contain the complete compiled rule, decompiled text, compiler/parser
hashes or authoritative lease history required to reuse a compiled result or
transfer a claim. Importing its `sealed` or `claimed` flag into local execution
state would therefore suppress necessary compilation or adopt an unverified
remote claim.

`SpanCache.upsert_remote_resume` now reads the relevant parquet columns once in
a transaction. For a matching dataset it reports distinct remote status
observations whose nonblank source hashes match local spans. It preserves all
local spans, seals, terms, claims, compiler snapshots and task-board rows. It
imports only new compatible agent observations, with explicit false admission
and formalization flags. Duplicate identical observations are idempotent;
conflicting agent observations reject the transaction. The existing ingest
consumer's `sealed`, `gaps` and `claimed` mutation counters remain present and
return zero. Additive observation fields describe what was seen.

The earlier importer could leave partial updates on failure, fail on ordinary
shared terms, and miss new agents because of an ambiguous SQL correlation. The
new path does not import terms or compile/claim state, correlates agent IDs
explicitly, and rolls back a failed import.

`skip_compile` also rejects absent, malformed or non-object stored rule payloads
and requeues those rows when accessed. Locally stored valid JSON objects,
including `{}`, keep their existing behavior. This is an access-time check;
no live database was scanned, migrated or recertified. Existing unobserved rows
are not established as correct by this code change.

The supervisor's new `ready_task_cids` field is a sorted per-goal observation.
A second read-only helper identifies ready tasks under parked goals for callers
to exclude from claims. Neither helper claims tasks, reopens held goals or changes
admission. Small isolated SQLite task-store tests check those properties without invoking the accelerate
service. The existing Grok status assertions against the broader supervisor flow
are preserved separately from that focused fixture.

The publication cutoff for `tests/unit/logic/test_supervisor_loop.py` is the
reviewed 27,521-byte snapshot with SHA256
`34ae120d780f5bfb730df324b5a0d1ee62a5f42a92402636338c8f24ecbf53e9`,
archived before repair under
`workspace/test-logs/federal-corpus-audits/campaign-grok-resume-repair-20260926/pre-fix/tests/unit/logic/test_supervisor_loop.py`.
The newer live file adds `_assert_claim_skips_parked_goal`, which invokes the
accelerator daemon and expects a claim exclusion available only in its modified
working tree. That implementation is absent from the dataset's committed
accelerator gitlink `91a1253c24a023c2f113d4549fecbfa042666464` and the parent's
committed accelerator gitlink `91cbd5244eb214e6ec675c003d8313f4ee9ac699`.
The live test and accelerator files remain untouched. The new claim integration
assertion is excluded from this publication and its qualification; publishing
the read-only helper does not establish that a committed daemon uses it.

Two supplemental preflights stopped before resource admission when new
Grok edits appeared. The successful fresh capture includes the reviewed
supervisor helper. The separate entity-queue feature remains outside the
publication: its source, test and ingest script are recorded as nonexecuted
workspace context, not qualified by these checks. The publication uses an explicit reviewed file list and preserves that
ongoing work in the live checkout.

This does not supply cross-process training leases through checkpoint exchange.
Those belong to the single owner and its durable DuckDB/Quack control plane.
An optimization that reuses remote compile results needs an immutable complete
receipt with matching source and producer identity, independently validated
before local cache acceptance. That remains separate work.

Only `lake build <Lib>` supplies a Lean admit. No checkpoint row, cache seal,
supervisor status or autoencoder completion changes that rule. The Constitution
remains unformalized.

## Captured validation

The [test receipt](evidence/autoencoder_control_plane_plan/campaign-grok-resume-tests-20260926-r1.json)
records 24 span-cache cases, two isolated supervisor-helper cases, seven
semantic/tree-pin/empty-vocabulary cases, and three canonical/typed pilot cases.
All 36 passed. Neither the archived broader supervisor test nor its newer live
version was selected. The parser's 24-hour deadline improvement remains, and
the canonical pilot compares each case and loss component against the unchanged
historical baseline. The typed pilot retains its 0.915 forward threshold and
1.000 cycle threshold.

The [audit](evidence/autoencoder_control_plane_plan/campaign-grok-resume-audit-20260926-r1.json)
passed the 60-second quiet gate and unchanged parent/child before-and-after
inventories of 7,777 package files and 1,297 dependencies. The nine B2 files
also matched the passed 486-case capture. Test wall time was 15.774 seconds;
the guarded capture took 103.170 seconds. These are regression-test timings,
not legal-IR speed measurements. Protected checkpoints and receipts stayed
unchanged. The [resource release](evidence/autoencoder_control_plane_plan/campaign-grok-resume-release-20260926-r1.json)
confirms release of reservation `5b9e5700b0224f7eaa67499ba3329501`. Its final
charge was 35,816,275 bytes, including a conservative 30 MB fixture allowance.
No native training, external prover, Lake build, live database migration,
DuckLake write or Hugging Face upload ran in this capture.
